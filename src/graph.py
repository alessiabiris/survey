#imports
from __future__ import annotations

import json
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, END

from .schema import Blueprint, SurveyInstrument, QAReport
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

#converts pydantic model to json schema 
def _json_schema(model_cls) -> str:
    return json.dumps(model_cls.model_json_schema(), indent=2)


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
    max_iters = state.get("max_iters", 1) #limit?
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

    #STEP 2: extract fixes from QA report 
    qa = state.get("qa") or {}
    fixes = "\n".join([f"- {x}" for x in (qa.get("suggested_fixes") or [])]) or "- (No specific fixes provided; improve clarity/neutrality and meet constraints.)"

    #STEP 3: put the fixes into the project brief 
    augmented_brief = state["project_brief"] + "\n\nQA-required fixes:\n" + fixes
    state["project_brief"] = augmented_brief

    #STEP 4: re run generation with the QA fixes in the brief
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
    max_iters: int = 1,
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
    # Convert to SurveyState
    current_state: SurveyState = {**state}
    
    # Add human notes
    current_state["human_notes"] = human_notes
    current_state["human_revision_count"] = current_state.get("human_revision_count", 0) + 1
    
    # Generate revised survey using human notes
    user = HUMAN_REVISE_USER.format(
        blueprint_json=json.dumps(current_state["blueprint"], indent=2),
        survey_json=json.dumps(current_state["survey"], indent=2),
        human_notes=human_notes,
        max_questions=current_state["max_questions"],
    )
    
    out = chat_json(GENERATOR_SYSTEM, user)
    survey = SurveyInstrument.model_validate(out)
    current_state["survey"] = survey.model_dump()
    
    # Run QA on the revised survey
    current_state = qa_node(current_state)
    
    return current_state


############################# FLOW SUMMARY ######################

#1 USER fills in form in Streamlit 

#2 run_survey_graph () - creates initial survey state (the shared memory)

#3 PLANNER thinks and outputs BLUEPRINT 

#4 GENERATOR writes and outputs INITIAL SURVEY 

#5 QA REVIEWS and outputs QA report 

#6 human review
