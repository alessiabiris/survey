#imports
from __future__ import annotations

import json
from typing import TypedDict, Optional, List, Dict, Any

from langgraph.graph import StateGraph, END

from .schema import Blueprint, SurveyInstrument, QAReport, HumanReview
from .llm import chat_json
from .prompts import (
    PLANNER_SYSTEM, PLANNER_USER,
    GENERATOR_SYSTEM, GENERATOR_USER,
    QA_SYSTEM, QA_USER, HUMAN_REVISE_USER,
)

#shared memory that passes through all nodes
#each node reads what it needs and writes its output back
class SurveyState(TypedDict, total=False):
    #INPUTS
    project_brief: str
    audience: str
    max_questions: int
    min_questions: int
    max_iters: int
    iter_count: int

    #OUTPUT - by agent
    blueprint: dict
    survey: dict
    qa: dict

    #HUMAN REVIEW
    human_notes: str
    human_revision_count: int

def _json_schema(model_cls) -> str:
    return json.dumps(model_cls.model_json_schema(), indent=2)


def _count_questions_from_dict(survey: Dict[str, Any]) -> int:
    """Count questions from a plain dict survey payload."""
    total = 0
    for sec in survey.get("sections", []) or []:
        total += len(sec.get("questions") or [])
    return total


def _validate_survey_structure(
    survey: SurveyInstrument,
    min_questions: int,
    max_questions: int,
) -> None:
    """
    Run additional structural checks that go beyond Pydantic validation.
    Raises ValueError with a human-readable message if something is wrong.
    """
    sections: List[Dict[str, Any]] = [s.model_dump() for s in survey.sections]

    if not sections:
        raise ValueError("Generated survey has no sections.")

    # No empty sections
    for sec in sections:
        if not (sec.get("questions") or []):
            raise ValueError(f"Section '{sec.get('title')}' has no questions.")

    # Question count bounds
    total_q = _count_questions_from_dict({"sections": sections})
    if total_q < min_questions or total_q > max_questions:
        raise ValueError(
            f"Generated survey has {total_q} questions, "
            f"which is outside the allowed range [{min_questions}, {max_questions}]."
        )

    # Unique question IDs and non-empty text
    seen_ids: set[str] = set()
    for sec in sections:
        for q in sec.get("questions") or []:
            qid = q.get("id")
            text = (q.get("text") or "").strip()
            if not qid or not isinstance(qid, str):
                raise ValueError("Every question must have a non-empty string id (e.g. 'Q1').")
            if qid in seen_ids:
                raise ValueError(f"Duplicate question id detected: '{qid}'.")
            seen_ids.add(qid)
            if not text:
                raise ValueError(f"Question '{qid}' has empty text.")


######################PLANNER NODE #####################

#FLOW: user inputs --> fill prompt --> LLM --> validate --> save blueprint
#output the blueprint

def planner_node(state: SurveyState) -> SurveyState:
    user = PLANNER_USER.format(
        project_brief=state["project_brief"],
        audience=state["audience"],
        max_questions=state["max_questions"],
        min_questions=state["min_questions"],
    )

    #STEP 3: call the LLM 
    out = chat_json(PLANNER_SYSTEM, user)
    
    #STEP 4: validate output against schema
    bp = Blueprint.model_validate(out)

    #STEP 5: save to state (the shared memory)
    state["blueprint"] = bp.model_dump()
    return state


##############################GENERATOR NODE #########################

#using the blueprint and the user inputs --> generates the survey title, intro, sections, questions etc
def generator_node(state: SurveyState) -> SurveyState:
    user = GENERATOR_USER.format(
        blueprint_json=json.dumps(state["blueprint"], indent=2),
        project_brief=state["project_brief"],
        max_questions=state["max_questions"],
        min_questions=state["min_questions"], 
    )
    #STEP 3: call the LLM 
    out = chat_json(GENERATOR_SYSTEM, user)

    #STEP 4: validate
    survey = SurveyInstrument.model_validate(out)

    #STEP 4b: custom structural checks beyond schema validation
    _validate_survey_structure(
        survey=survey,
        min_questions=state["min_questions"],
        max_questions=state["max_questions"],
    )

    #STEP 5: save to the shared memory 
    state["survey"] = survey.model_dump()
    return state

##################################QA NODE#############################

#QA checks:
#survey matches blueprint?
#blueprint matches brief?
#biased questions?
#too many questions?

#output: passed or not passed (if not then suggests fixes)

def qa_node(state: SurveyState) -> SurveyState:
    user = QA_USER.format(
        project_brief=state["project_brief"],
        blueprint_json=json.dumps(state["blueprint"], indent=2),
        survey_json=json.dumps(state["survey"], indent=2),
        max_questions=state["max_questions"],
    )
    out = chat_json(QA_SYSTEM, user)
    qa = QAReport.model_validate(out)
    state["qa"] = qa.model_dump()
    return state


#####################AUTO LOOP DECISION  #########################

def revise_or_end(state: SurveyState) -> str:
   
    iters = state.get("iter_count", 0) #how many times we revise
    max_iters = state.get("max_iters", 3) #limit?
    qa = state.get("qa") or {}
    passed = bool(qa.get("passed", False)) #did QA pass?

    if passed:
        return END #if passed then done
    if iters >= max_iters:
        return END #if hit max iterations stop anyway
    return "revise" #if QA failed and still iterations revise 

################## REVISE NODE ###############################

def revise_node(state: SurveyState) -> SurveyState:
   
    #STEP 1: increment interation counter
    state["iter_count"] = state.get("iter_count", 0) + 1

    #STEP 2: extract fixes and issues from QA report 
    qa = state.get("qa") or {}
    issues = qa.get("issues") or []
    fixes = qa.get("suggested_fixes") or []

    issues_text = "\n".join([f"- {x}" for x in issues]) or "None explicitly listed."
    fixes_text = "\n".join([f"- {x}" for x in fixes]) or "- (No specific fixes provided; improve clarity/neutrality and meet constraints.)"

    #STEP 3: build an augmented brief describing what must change
    augmented_brief = (
        state["project_brief"]
        + "\n\nPrevious QA issues:\n"
        + issues_text
        + "\n\nQA-required fixes:\n"
        + fixes_text
    )
    state["project_brief"] = augmented_brief

    #STEP 4: re run generation with the QA-informed brief
    return generator_node(state)


########################## connect everything ########################

def build_graph():
    g = StateGraph(SurveyState)

    #register all nodes 
    g.add_node("planner", planner_node)
    g.add_node("generator", generator_node)
    g.add_node("qa", qa_node)
    g.add_node("revise", revise_node)

    #define flow 
    #planner --> generator --> qa --> passed? --> if yes - end / if no - revise and then back to generator 
    g.set_entry_point("planner")
    g.add_edge("planner", "generator")
    g.add_edge("generator", "qa")
    g.add_conditional_edges("qa", revise_or_end, {"revise": "revise", END: END})
    g.add_edge("revise", "qa")

    return g.compile()

###########################run function #####################
#complies the graph
#create initial state from user inputs
#runs entire workflow
#return final state

def run_survey_graph(
    project_brief: str,
    audience: str,
    max_questions: int = 20,
    min_questions: int = 15, 
    max_iters: int = 3,
):
    app = build_graph()
    init: SurveyState = {
        "project_brief": project_brief.strip(),
        "audience": audience.strip(),
        "max_questions": int(max_questions),
        "min_questions": int(min_questions),
        "max_iters": int(max_iters),
        "iter_count": 0,
    }
    final_state = app.invoke(init)
    return final_state


##################### HUMAN REVISION #####################

def run_human_revision(
    state: dict,
    human_notes: str,
) -> dict:
    # STEP 1: Validate human input properly using HumanReview class
    review = HumanReview.from_input(human_notes)

    # STEP 2: Convert to SurveyState and update revision count
    current_state: SurveyState = {**state}
    current_state["human_notes"] = review.notes
    current_state["human_revision_count"] = current_state.get("human_revision_count", 0) + 1

    # STEP 3: Extract previous QA issues to give the agent full context
    qa = current_state.get("qa") or {}
    previous_issues = qa.get("issues") or []
    qa_issues_text = "\n".join([f"- {issue}" for issue in previous_issues]) if previous_issues else "None"

    # STEP 4: Build prompt with FULL context — blueprint, survey, QA issues, and human notes
    # The agent sees everything so it can make targeted changes without rediscovering problems
    user = HUMAN_REVISE_USER.format(
        blueprint_json=json.dumps(current_state["blueprint"], indent=2),
        survey_json=json.dumps(current_state["survey"], indent=2),
        qa_issues=qa_issues_text,
        human_notes=review.notes,
        max_questions=current_state["max_questions"],
    )

    # STEP 5: Single generation pass — no QA loop, trust the human reviewer
    out = chat_json(GENERATOR_SYSTEM, user)
    survey = SurveyInstrument.model_validate(out)

    # Apply the same structural checks used in the automated path
    _validate_survey_structure(
        survey=survey,
        min_questions=current_state["min_questions"],
        max_questions=current_state["max_questions"],
    )
    current_state["survey"] = survey.model_dump()

    # STEP 6: Run one single QA check for the report — but do NOT loop on failure
    # The human has reviewed this — we show the QA report but do not auto-revise
    current_state = qa_node(current_state)

    return current_state


############################# FLOW SUMMARY ######################

#1 USER fills in form in Streamlit 

#2 run_survey_graph () - creates initial survey state (the shared memory)

#3 PLANNER thinks and outputs BLUEPRINT 

#4 GENERATOR writes and outputs INITIAL SURVEY 

#5 QA REVIEWS and outputs QA report 

#6 human review
