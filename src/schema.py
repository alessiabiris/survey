#data structures - what are we passing around

from __future__ import annotations
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field

#type of questions 
QuestionType = Literal[
    "single_choice",
    "multi_choice",
    "multiple_choice",
    "likert_5", #1-5 scale
    "likert_7", #1-7 scale
    "free_text",
    "numeric", #numeric input
    "date", 
    "nps_0_10", #score 0 to 10 
]

#define conditional logic for surveys
#so if "no" q3 then skip to q10 for example
class SkipRule(BaseModel):
    if_question_id: str
    operator: Literal["equals", "not_equals", "in", "not_in", "gte", "lte"]
    value: Any
    goto_question_id: str

#Question - defines everything about a question 
class Question(BaseModel):
    id: str = Field(..., description="Unique question id, e.g. Q1")
    text: str #actual question text
    type: QuestionType #one of the above question type 
    options: Optional[List[str]] = None #answer choices
    required: bool = True #if mandatory
    # Metadata for analysis readiness 
    # this part says what each question measures and how to group it in reports 
    topic: Optional[str] = Field(None, description="What this question measures")
    analysis_tag: Optional[str] = Field(None, description="How it will be used in analysis")
    notes: Optional[str] = None
    skip_rules: Optional[List[SkipRule]] = None

#splits in sections eg Profile of respondents etc
class Section(BaseModel):
    title: str
    description: Optional[str] = None
    questions: List[Question]

#final output
class SurveyInstrument(BaseModel):
    sections: List[Section] #sections 

#what to measure and how the survey should be structured 
#its a plan before the llm writes questions 
#this makes the LLM AGENTIC - it thinks first then writes 
#generator uses the blueprint to create the actual survey 
class Blueprint(BaseModel):
    goals: List[str]  #what are we trying to learn from the survey
    target_audience: str #who takes the survey
    topics_to_measure: List[str] #what concepts to measure (satisfaction, trust etc)
    sections: List[str] #suggested sections
    question_types: List[str] #recommended question types
    max_questions: int = Field(..., ge=5, le=80) 
    notes: Optional[str] = None

#the Agent loops 3 times over itself to check for mistakes
class QAReport(BaseModel):
    passed: bool #did it pass review?
    issues: List[str] = Field(default_factory=list) #whats wrong
    suggested_fixes: List[str] = Field(default_factory=list) #how to fix it 

#human review 
#so the final output of the agent -- we get to review it and if approved perfect if not write notes of what to change
class HumanReview(BaseModel):
    approved: bool = False
    notes: Optional[str] = None
