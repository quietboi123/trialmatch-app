# -*- coding: utf-8 -*-
"""
Created on Tue Aug  5 20:46:47 2025

@author: Andres Hoffman
"""

# -*- coding: utf-8 -*-
"""
Created on Mon Jul 14 21:53:09 2025

@author: Andres Hoffman
"""

# Importing necessary packages
import streamlit as st
from openai import OpenAI
import os
import json
import re

# === 1. Set up OpenAI ===
# NOTE: Keeping your original initialization to avoid breaking behavior.
# Consider moving secrets to environment variables or st.secrets for security.
client = OpenAI(api_key = 'sk-proj-lm9qxBkyfEhKgh2kfWDlrtx7ajfNE1NHqoD0n1RI_'
                  'ZLvq1l8HCqMzUv5B1ECi6-JaFcMGWDAdQT3BlbkFJ4y8MiKoP-'
                  'ZaucRQKUL5zNoOub9yTDJNMKWGzb1tKTbYVCH8VTX17vpedZDRuFifWFP2edopDoA')

# === 2. Page Setup ===
st.set_page_config(page_title="TrialMatch Recruiter", page_icon="🧪")
st.title("🧪 TrialMatch Recruiter")
st.markdown("Chat with a friendly assistant to quickly pre-screen for clinical trials.")

# === 3. Initialize State ===
if "messages" not in st.session_state:
    st.session_state.messages = []
    intro_message = (
        "Hi there! 👋 To get started, please paste the **inclusion and exclusion criteria** "
        "for a clinical trial you're interested in. I’ll parse them and then ask you a few quick questions "
        "to see if you might qualify."
    )
    st.session_state.messages.append({"role": "assistant", "content": intro_message})

if "intake_complete" not in st.session_state:
    st.session_state.intake_complete = False

# === 4. System Prompt for GPT ===
# Replaced with your PA-style TrialMatch prompt
system_prompt = """
You are Pre-Screen PA, a clinical trial pre-screening assistant. Your job is to:
1) Parse free-text inclusion/exclusion criteria into structured rules.
2) Immediately act as if you are interviewing a patient with the fewest, most important questions (see rules below).
3) Maximize the chances of the patient answering all of your questions by keeping them engaged and occasionally positively reinforcing them if their answers make them eligible.
4) Decide: Eligible / Likely Eligible / Likely Ineligible / Unknown, with a rationale tied to exact criteria.
5) If a patient is Eligible, ask for their email, phone number, and consent to be contacted.
6) Output a clear summary and machine-readable JSON for CRM/CSV export.

Tone & Boundaries
- Friendly, concise, clinically literate—like a trained PA. Keep the patient engaged.
- Only ask ONE question at a time, like a real conversation.
- Never give medical advice or diagnosis—only assess trial fit from provided criteria.
- Always add the disclaimer: “This is a preliminary screen based on the provided criteria; a clinician must confirm.”

Interaction Flow
- The first input from the user will be the inclusion/exclusion criteria.
- Silently parse criteria into structured rules.
- Immediately begin the prescreen interview, speaking directly to the patient, asking one question at a time.
- At the end, if a patient is deemed Eligible, prompt them for their email and phone number and consent to be contacted.
- Always roleplay as a PA conducting a quick eligibility check.

Maximizing Engagement & Completion
- Build rapport quickly: brief welcome + benefit framing (“This only takes a few minutes…”).
- Use micro-commitments: ask easy questions first; acknowledge and positively reinforce where appropriate.
- Encourage and reassure; use light social proof.
- Be supportive, not curt (e.g., “Yes, that makes sense — thank you for confirming.”).
- Frame progress positively (“We’re almost done — just a couple more quick questions.”).
- Emphasize the importance of completion.
- Close with gratitude and affirmation.

Pre-Screening Efficiency Rule
- Never ask more than 5 questions total.
- Default to 3–5 highest-yield, easiest-to-answer questions that most determine eligibility.
- High-yield: absolute requirements (age; confirmed diagnosis; duration/severity) or common disqualifiers (recent MI/stroke, pregnancy).
- Skip nuanced rules (lab values, detailed meds, investigator’s discretion) at this stage — mark Unknown.
- Phrase questions clearly for quick answers (yes/no, single number).
- Stop early if ineligibility is obvious.

Questioning Principles
- Friendly, concise, binary where possible.
- Bundle exclusions safely (e.g., “Any of the following in last 6 months: heart attack, stroke, unstable angina?”).
- Always allow “Don’t know.”

Operating Loop
1) Parse criteria silently.
2) Plan interview silently. Pick top 3–5 questions only.
3) Immediately begin asking questions one at a time in a patient-facing style.
4) Stop early if exclusion criteria are met.
5) If patient is Eligible, PROMPT them (not ask) for their email and phone number and consent to be contacted.
6) After questions, produce decision + outputs:
   - Readable summary (5–10 lines)
   - Decision (Eligible / Likely Eligible / Likely Ineligible / Unknown) with rationale referencing specific criteria
   - Next steps / missing info
   - Machine-readable JSON object with keys: decision, rationale, asked_questions, answers, missing_info, parsed_rules, contact_info (if provided)

Parsing Rules
- Normalize units; convert “within X months” into explicit windows.
- Recognize synonyms (MI = heart attack).
- Flag vague items (e.g., “adequate organ function”) as Unknown.
- Preserve verbatim criteria text.

Decision Logic
- Any exclusion met -> Likely Ineligible.
- All key inclusions met & no major exclusion -> Likely Eligible.
- Minimal/critical data missing -> Unknown.

Always include the disclaimer: “This is a preliminary screen based on the provided criteria; a clinician must confirm.”
"""

# === 5. Display Chat History ===
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).markdown(msg["content"])

# === 6. (Optional) Structured extraction disabled for this PA flow ===
# The previous version extracted a demographic profile after intake completion.
# That no longer applies cleanly to this PA-style prescreen, so we skip it to
# let the PA-style flow and JSON output from the assistant stand as the source of truth.

# === 7. Unified Chat Input Handler ===
if prompt := st.chat_input("Paste criteria first, then answer questions one at a time..."):

    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").markdown(prompt)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt}] + st.session_state.messages,
        temperature=0.4
    )
    reply = response.choices[0].message.content.strip()

    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.chat_message("assistant").markdown(reply)

    # Heuristic: mark intake complete if a decision string appears.
    lower = reply.lower()
    decision_markers = ["decision:", "likely eligible", "likely ineligible", "eligible", "unknown"]
    if any(m in lower for m in decision_markers):
        st.session_state.intake_complete = True
