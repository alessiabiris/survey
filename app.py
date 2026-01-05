import os
import json
import streamlit as st
from dotenv import load_dotenv

from src.graph import run_survey_graph, run_human_revision
from src.render import extract_codebook, count_questions

load_dotenv()

st.set_page_config(page_title="EKOS Survey Designer", layout="wide")
st.title("EKOS Survey Designer")

if "survey_state" not in st.session_state:
    st.session_state.survey_state = None
if "review_phase" not in st.session_state:
    st.session_state.review_phase = False

######## SIDEBAR - CONFIGURATION ##########
with st.sidebar:
    st.header("Configuration")

    default_max_q = int(os.getenv("DEFAULT_MAX_QUESTIONS", "20"))

    max_questions = st.slider("Max questions", min_value=5, max_value=60, value=default_max_q, step=1)
    min_questions = max(max_questions - 5, int(max_questions * 0.8))
   
    st.divider()
    if st.button("Start New Survey", use_container_width=True):
        st.session_state.survey_state = None
        st.session_state.review_phase = False
        st.rerun()

######## INPUT FORM ##########
project_brief = st.text_area("Project brief", height=220)
audience = st.text_input("Target audience")

if not st.session_state.review_phase:
    run = st.button("Generate survey", type="primary", use_container_width=True)
else:
    run = False
    st.info("Survey generated. Review below.")

#run 
if run:
    if not project_brief.strip():
        st.error("Please paste a project brief first.")
        st.stop()

    with st.spinner("Running agentic workflow (planner → generator → QA)..."):
        try:
            final_state = run_survey_graph(
                project_brief=project_brief,
                audience=audience,
                max_questions=max_questions,
                min_questions=min_questions,
                max_iters=3,
            )
            st.session_state.survey_state = final_state
            st.session_state.review_phase = True
            st.rerun()
        except Exception as e:
            st.error(str(e))
            st.stop()

if st.session_state.survey_state:
    final_state = st.session_state.survey_state
    
    blueprint = final_state.get("blueprint", {})
    survey = final_state.get("survey", {})
    qa = final_state.get("qa", {})

    st.success("Survey generated. Please review.")
    qcount = count_questions(survey)
    
    human_rev_count = final_state.get("human_revision_count", 0)
    if human_rev_count > 0:
        st.info(f"Questions: {qcount} (max: {max_questions}) | Human revisions: {human_rev_count}")
    else:
        st.info(f"Questions: {qcount} (max: {max_questions})")

    tab1, tab2, tab3, tab4 = st.tabs(["Blueprint", "Survey (formatted)", "Codebook", "QA report"])

    with tab1:
        st.subheader("Blueprint")
        st.json(blueprint)

    with tab2:
        st.subheader("Survey")
        for sec in survey.get("sections", []):
            st.markdown(f"## {sec.get('title')}")
            for q in sec.get("questions", []):
                st.markdown(f"**{q.get('id')}** — {q.get('text')}")
                qtype = q.get("type")
                opts = q.get("options") or []
                if qtype in ("single_choice", "likert_5", "likert_7"):
                    st.radio("Select one:", opts, key=f"{q.get('id')}_radio", disabled=True)
                elif qtype == "multi_choice":
                    st.write("Select all that apply:")
                    for opt in opts:
                        st.checkbox(opt, key=f"{q.get('id')}_{opt}", disabled=True)
                elif qtype == "free_text":
                    st.text_area("Your answer:", key=f"{q.get('id')}_text", disabled=True, height=80)
                elif qtype == "numeric":
                    st.number_input("Enter a number:", key=f"{q.get('id')}_num", disabled=True)
                st.markdown("---")

    with tab3:
        st.subheader("Codebook")
        codebook_df = extract_codebook(survey)
        st.dataframe(codebook_df, use_container_width=True)
        st.download_button(
            "Download codebook.csv",
            data=codebook_df.to_csv(index=False).encode("utf-8"),
            file_name="codebook.csv",
            mime="text/csv",
        )

    with tab4:
        st.subheader("QA report")
        st.json(qa)
        if not qa.get("passed", False):
            st.warning("QA did not fully pass. Review issues above or provide revision notes below.")

    st.divider()
    st.subheader("Human Review")
    
    col_approve, col_revise = st.columns([1, 1])
    
    with col_approve:
        st.write("**Happy with the survey?**")
        if st.button("Approve & Finish", type="primary", use_container_width=True):
            st.balloons()
            st.success("Survey approved! Download using the buttons above.")
            st.session_state.review_phase = False

    with col_revise:
        st.write("**Want changes?**")
        human_notes = st.text_area(
            "Your revision notes",
            height=120,
            key="human_notes_input"
        )
        
        if st.button("Revise with Notes", use_container_width=True):
            if not human_notes.strip():
                st.error("Please enter your revision notes first.")
            else:
                with st.spinner("Revising survey based on your notes..."):
                    try:
                        revised_state = run_human_revision(
                            state=st.session_state.survey_state,
                            human_notes=human_notes,
                        )
                        st.session_state.survey_state = revised_state
                        st.rerun()
                    except Exception as e:
                        st.error(f"Revision failed: {str(e)}")
