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
client = OpenAI(api_key = 'sk-proj-lm9qxBkyfEhKgh2kfWDlrtx7ajfNE1NHqoD0n1RI_'
                  'ZLvq1l8HCqMzUv5B1ECi6-JaFcMGWDAdQT3BlbkFJ4y8MiKoP-'
                  'ZaucRQKUL5zNoOub9yTDJNMKWGzb1tKTbYVCH8VTX17vpedZDRuFifWFP2edopDoA')

# === 2. Page Setup ===
st.set_page_config(page_title="TrialMatch Recruiter", page_icon="🧪")
st.title("🧪 TrialMatch Recruiter")
st.markdown("Chat with a friendly assistant to see what clinical trials might be right for you.")

# === 3. Initialize State ===
if "messages" not in st.session_state:
    st.session_state.messages = []
    intro_message = (
        "Hi there! 👋 I'm here to help you explore clinical trials that may be a good fit for you.\n\n"
        "Let’s get started. What health condition are you researching today?"
    )
    st.session_state.messages.append({"role": "assistant", "content": intro_message})
if "user_profile" not in st.session_state:
    st.session_state.user_profile = {}
if "intake_complete" not in st.session_state:
    st.session_state.intake_complete = False

# === 4. System Prompt for GPT ===
system_prompt = """
You are a friendly medical assistant helping a patient find clinical trials.
Ask one intake question at a time. Your goal is to collect:
- Condition (disease)
- Age
- Gender
- Zip code
- Whether they've been officially diagnosed
- Any prior treatments

Be clear and conversational. Only ask one question at a time.
Once you’ve collected all fields, say “Thanks! I have everything I need.” and stop.
"""

# === 5. Display Chat History ===
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).markdown(msg["content"])

# === 6. Extract Structured Profile After Intake Completion ===
if st.session_state.intake_complete and not st.session_state.user_profile:
    extraction_prompt = """
You are an assistant that extracts structured data from a medical intake chat.

From the chat below, return a JSON object with the following fields:
- condition (string)
- age (integer)
- gender (string)
- zip_code (string)
- diagnosed (boolean)
- treatment_history (string)

Only return a valid JSON object. No explanation or extra text.
"""

    # Build readable chat history for GPT
    full_chat = ""
    for msg in st.session_state.messages:
        full_chat += f"{msg['role']}: {msg['content']}\n"

    # Send to GPT for extraction
    extraction_response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": extraction_prompt},
            {"role": "user", "content": full_chat}
        ],
        temperature=0
    )

    profile_text = extraction_response.choices[0].message.content.strip()

    # Remove markdown code block formatting like ```json ... ```
    if profile_text.startswith("```"):
        profile_text = re.sub(r"^```(?:json)?\s*", "", profile_text)
        profile_text = re.sub(r"\s*```$", "", profile_text)

    try:
        user_profile = json.loads(profile_text)
        st.session_state.user_profile = user_profile
        st.success("✅ Your profile has been created!")

        # Generate a friendly summary
        summary = (
            f"Here's what I have so far:\n\n"
            f"- **Condition:** {user_profile['condition']}\n"
            f"- **Age:** {user_profile['age']}\n"
            f"- **Gender:** {user_profile['gender']}\n"
            f"- **Zip Code:** {user_profile['zip_code']}\n"
            f"- **Diagnosed:** {'Yes' if user_profile['diagnosed'] else 'No'}\n"
            f"- **Treatment History:** {user_profile['treatment_history']}\n\n"
            "Does everything look correct?"
        )

        st.session_state.messages.append({"role": "assistant", "content": summary})
        st.chat_message("assistant").markdown(summary)

    except Exception as e:
        st.error("❌ Could not parse the response as valid JSON.")
        st.exception(e)

# === 7. Unified Chat Input Handler ===
if prompt := st.chat_input("Type your response here..."):

    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").markdown(prompt)

    # CASE 1: Intake not complete – continue asking intake questions
    if not st.session_state.intake_complete:

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system_prompt}] + st.session_state.messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content.strip()

        st.session_state.messages.append({"role": "assistant", "content": reply})
        st.chat_message("assistant").markdown(reply)

        if "i have everything i need" in reply.lower():
            st.session_state.intake_complete = True
            st.success("Intake complete! Generating your profile...")
            st.rerun()

    # CASE 2: Intake complete, profile extracted, waiting for user confirmation
    elif st.session_state.user_profile and not st.session_state.get("profile_confirmed"):

        if any(word in prompt.lower() for word in ["yes", "correct", "looks good", "yep", "that's right"]):
            st.session_state.profile_confirmed = True
            st.success("🎉 Great! Your profile is finalized. Let’s find you some matching trials.")
            st.chat_message("assistant").markdown("🎉 Great! Your profile is finalized. Let’s find you some matching trials.")
            
            # === Generate mock trial match ===
            trial_prompt = f"""
            You are a clinical trial assistant. Based on the following patient profile, generate a concise and realistic mock clinical trial listing that they may qualify for.
            
            Patient profile:
            - Condition: {st.session_state.user_profile['condition']}
            - Age: {st.session_state.user_profile['age']}
            - Gender: {st.session_state.user_profile['gender']}
            - Zip Code: {st.session_state.user_profile['zip_code']}
            - Diagnosed: {st.session_state.user_profile['diagnosed']}
            - Treatment History: {st.session_state.user_profile['treatment_history']}
            
            Format your response like this:
            
            **Trial Title:** [Name of the trial]  
            **Condition:** [Condition]  
            **Location:** [City, State or general region]  
            **Sponsor:** [Institution or sponsor]  
            **Summary:** [1–2 sentence layman summary of the trial]  
            **Inclusion Criteria:** [Bullet points of simplified eligibility]  
            **Contact:** [mock contact email or phone number]
            """

            trial_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "system", "content": trial_prompt}],
                temperature=0.7
            )
            trial_summary = trial_response.choices[0].message.content.strip()
        
            # Show trial summary
            st.chat_message("assistant").markdown(trial_summary)
            
        else:
            st.warning("Thanks for letting me know. Let's go back and fix the details you mentioned.")
            st.chat_message("assistant").markdown(
                "Thanks for letting me know. We can go back and revise the info. "
                "For now, please describe what you'd like to change."
            )

    # CASE 3: Shouldn't happen often — intake complete but profile not extracted yet
    elif st.session_state.intake_complete and not st.session_state.user_profile:
        st.warning("Generating your profile now...")
