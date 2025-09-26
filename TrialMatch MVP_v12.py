# -*- coding: utf-8 -*-
"""
TrialMatch Recruiter (v8, preset criteria, hidden JSON, contact form, auto-rerun fix)
- Pre-set inclusion/exclusion criteria (no user paste)
- Hides machine JSON from the UI, still saves to Supabase
- Switches to a 3-field form (email, phone, consent) when contact info is needed
- Immediately shows the form on the same turn (st.rerun) so the chat doesn't look "stuck"
"""

import os  # <-- added
import streamlit as st
import streamlit.components.v1 as components  # <-- for autoscroll
# from openai import OpenAI  # (moved into cached factory below)
# from supabase import create_client, Client  # <-- lazy-import inside get_supabase()
import json
import re
import base64
from datetime import datetime, timezone
from pathlib import Path

# ---- Page config (must be first Streamlit call) ----
st.set_page_config(
    page_title="trialmatches — Asthma Study Pre-Screen",
    page_icon="assets/TrialMatch_Logo.png",  # place a small 32x32 or 64x64 PNG here
    layout="centered",
)

# ===== Top-left site header logo (safe drop-in) =====
import base64
from pathlib import Path

# 1) Preferred: Streamlit native header logo (available on recent versions)
try:
    # Places the logo in the app’s header at the top-left (outside the centered page column).
    # If you want the logo to link to your home page, set link="https://trialmatch-app.onrender.com"
    st.logo("assets/TrialMatch_Logo.png")
    # Add a little breathing room below the header so content isn’t cramped
    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

except Exception:
    # 2) Fallback: CSS-based fixed top bar that spans the full page width
    def _img_b64(p: Path) -> str:
        with open(p, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    _logo = Path("assets/TrialMatch_Logo.png")
    logo_b64 = _img_b64(_logo) if _logo.exists() else ""

    st.markdown(
        f"""
        <style>
          /* Reserve space under the fixed bar so content doesn’t hide behind it */
          .block-container {{ padding-top: 72px; }}

          /* Full-width fixed bar pinned to the viewport, not the centered column */
          .tm-topbar {{
            position: fixed; top: 0; left: 0; right: 0; height: 56px;
            display: flex; align-items: center; gap: 12px;
            padding: 8px 16px;
            background: white;
            box-shadow: 0 1px 6px rgba(0,0,0,.08);
            z-index: 9999;
          }}
          .tm-topbar .tm-logo {{
            width: 36px; height: 36px;
            background-image: url('data:image/png;base64,{logo_b64}');
            background-size: contain; background-position: center left; background-repeat: no-repeat;
          }}
          .tm-topbar .tm-title {{
            font-weight: 700; font-size: 22px; line-height: 1; margin: 0;
          }}
        </style>

        <div class="tm-topbar">
          <div class="tm-logo"></div>
          <div class="tm-title">Check Your Eligibility for Local Asthma Studies</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
# ===== End top-left site header logo =====



# ===== Top-left fixed navbar (drop-in) =====

def _img_b64(p: Path) -> str:
    with open(p, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

_logo = Path("assets/TrialMatch_Logo.png")
logo_b64 = _img_b64(_logo) if _logo.exists() else ""

st.markdown(
    f"""
    <style>
      /* Fixed top bar spanning full page width */
      .tm-topbar {{
        position: fixed;
        top: 0; left: 0; right: 0;
        width: 100%;
        display: flex; align-items: center; gap: 12px;
        padding: 10px 16px;
        background: white;  /* or your theme color if preferred */
        box-shadow: 0 1px 6px rgba(0,0,0,.08);
        z-index: 9999;  /* keep it above Streamlit content */
      }}
      .tm-topbar img {{
        height: 32px;  /* adjust to taste (e.g., 40px) */
      }}
      .tm-topbar .tm-title {{
        font-weight: 700;
        font-size: 24px; /* ~text-3xl look */
        line-height: 1.2;
        margin: 0;
      }}
    </style>

    <div class="tm-topbar">
      {'<img src="data:image/png;base64,' + logo_b64 + '" alt="trialmatches logo"/>' if logo_b64 else ''}
      <div class="tm-title">Check Your Eligibility for Local Asthma Studies</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Spacer so the app content doesn't hide under the fixed bar
st.markdown("<div style='height:64px'></div>", unsafe_allow_html=True)
# ===== End top-left fixed navbar =====


# =========================
# 0) CONFIG: PRESET CRITERIA
# =========================
USE_PRESET_CRITERIA = True
CONTACT_TOKEN = "[CONTACT_INFO_FORM]"  # sentinel the model outputs to trigger the form

PRESET_CRITERIA = {
    "title": "Combination Short-Acting BroNchodilator and Inhaled Corticosteroid Rescue Therapy on Health Outcomes in Routine Care | NCT06422689",
    "inclusion": [
        "1. Adults aged 18 years and above as of enrollment date.",
	"2. At least 1 visit with primary or secondary diagnosis of asthma on or within 12 months prior to the enrollment date.",
	"3. At least 1 prescription filled for Short-acting beta-agonist (SABA)-only inhaler (i.e., albuterol-only or levalbuterol only inhalers) within 12 months before enrollment date.",
	"4. At least 1 asthma exacerbation within 12 months before enrollment date.",
	"5. Had both medical and pharmacy insurance coverage (e.g., Medicare, Medicaid, and commercial insurance) for at least 12 months before enrollment date and without foreseeable plans to discontinue insurance coverage within 12 months after enrollment date.",
	"6. Participants also need to meet each of the following inclusion criteria: 1. Willingness to use albuterol and budesonide as rescue as instructed by their physician, prescribing information, and United States instruction for use (USIFU). 2. Willingness to respond to quarterly safety inquiries. 3. Willingness to participate in quarterly electronic patient-reported outcome (PRO) surveys via email or text. 4. Physician decision that participant is eligible for treatment with albuterol and budesonide as rescue according to the approved United States prescribing information (USPI)."
    ],
    "exclusion": [
        "1. Conditions with major respiratory diagnoses including chronic obstructive pulmonary disease (COPD), cystic fibrosis, pulmonary fibrosis, bronchiectasis, respiratory tract cancer, bronchopulmonary dysplasia, sarcoidosis, lung cancer, interstitial lung disease, pulmonary hypertension, and tuberculosis in 12 months before the enrollment date.",
	"2. Inpatient admission or emergency department or urgent care visit due to asthma in the 10 days before enrollment date, or self-reported use of systemic corticosteroid for the treatment of asthma in the 10 days before enrollment date. Participants who were screen-failed due to this criterion may be re-screened once the participant is more than 10 days post asthma-related inpatient admission, emergency department or urgent care visit, or systemic corticosteroid use.",
	"3. Chronic use of oral corticosteroids (for any condition) within 3 months before enrollment date. Chronic use of oral corticosteroids is defined as: daily or every other day use for 14 days or longer.",
	"4. History of albuterol and budesonide as rescue use within 12 months before enrollment date.",
	"5. History of any malignancy (except non-melanoma neoplasms of skin) in 12 months before the enrollment date.",
	"6. For females only - currently pregnant or breastfeeding on enrollment date. Participants are excluded from the study if any of the following criteria apply."
    ],
}

def criteria_to_markdown(criteria: dict) -> str:
    inc = "\n".join(f"* {item}" for item in criteria.get("inclusion", []))
    exc = "\n".join(f"* {item}" for item in criteria.get("exclusion", []))
    title = criteria.get("title", "Trial Criteria")
    return (
        f"**{title}**\n\n"
        f"**Key Inclusion Criteria:**\n{inc}\n\n"
        f"**Key Exclusion Criteria:**\n{exc}"
    )

# =========================
# 1) CLIENTS (works on Streamlit & Render)
# =========================
def _get_secret(name_env: str, *secrets_path):
    """
    Prefer flat environment variables (Render, GH Actions, etc.).
    Fall back to nested st.secrets['section']['key'] used on Streamlit Cloud.
    """
    val = os.environ.get(name_env)
    if val:
        return val
    try:
        s = st.secrets
        for k in secrets_path:
            s = s[k]
        return s
    except Exception:
        return None

OPENAI_API_KEY = _get_secret("OPENAI_API_KEY", "openai", "api_key")
SUPABASE_URL = _get_secret("SUPABASE_URL", "supabase", "url")
SUPABASE_SERVICE_KEY = _get_secret("SUPABASE_SERVICE_KEY", "supabase", "service_key")

# Friendly validation with clear guidance
_missing = [n for n, v in [
    ("OPENAI_API_KEY", OPENAI_API_KEY),
    ("SUPABASE_URL", SUPABASE_URL),
    ("SUPABASE_SERVICE_KEY", SUPABASE_SERVICE_KEY),
] if not v]

if _missing:
    st.error(
        "Missing required configuration: "
        + ", ".join(_missing)
        + ". Set them as environment variables on Render, or add them to st.secrets "
          "(e.g., st.secrets['openai']['api_key'], st.secrets['supabase']['url'], "
          "st.secrets['supabase']['service_key'])."
    )
    st.stop()

# Initialize clients using resolved secrets (cached)
@st.cache_resource
def get_openai_client():
    from openai import OpenAI
    return OpenAI(api_key=OPENAI_API_KEY)

@st.cache_resource
def get_supabase():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

client = get_openai_client()

# =========================
# 2) HELPERS
# =========================
def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"yes", "y", "true", "t", "1", "consent", "agree", "agreed"}
    return False

def _normalize_decision(s: str) -> str:
    s = (s or "").strip().lower()
    if "likely ineligible" in s or "ineligible" in s:
        return "Likely Ineligible"
    if "likely eligible" in s:
        return "Likely Eligible"
    if s == "eligible" or ("eligible" in s and "likely" not in s and "ineligible" not in s):
        return "Eligible"
    if "unknown" in s:
        return "Unknown"
    return "Unknown"

def extract_last_json_block(text: str):
    """
    Parse the last JSON object from assistant reply.
    Supports ```json ...``` fenced or raw {...}.
    """
    try:
        blocks = re.findall(r"```(?:json)?\s*({[\s\S]*?})\s*```", text)
        candidate = blocks[-1] if blocks else re.findall(r"({[\s\S]*})", text)[-1]
        return json.loads(candidate)
    except Exception:
        return None

def strip_machine_json(text: str) -> str:
    """
    Hide machine JSON & the contact token from user-visible content.
    """
    t = re.sub(r"```(?:json)?\s*{[\s\S]*?}\s*```", "", text).strip()
    t = re.sub(r"\s*{[\s\S]*}\s*$", "", t).strip()
    t = t.replace(CONTACT_TOKEN, "").strip()
    return t

def persist_result(reply_text: str, session_id: str = None):
    """
    Saves to Supabase on ANY decision.
    Fields: created_at, trial_title, decision, rationale, asked_questions, answers,
            parsed_rules, contact_email, contact_phone, consent, session_id
    """
    sb = get_supabase()
    data = extract_last_json_block(reply_text)

    decision = "Unknown"
    rationale = "No JSON payload found."
    answers = None
    parsed_rules = None
    contact = {}
    trial_title = None
    questions = None

    if data:
        decision = _normalize_decision(data.get("decision"))
        rationale = data.get("rationale")
        answers = data.get("answers")
        parsed_rules = data.get("parsed_rules")
        contact = data.get("contact_info") or {}
        trial_title = (parsed_rules or {}).get("trial_title")
        questions = data.get("asked_questions")

    consent_val = _as_bool(contact.get("consent"))
    contact_email = contact.get("email")
    contact_phone = contact.get("phone")

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trial_title": trial_title,
        "decision": decision,
        "rationale": rationale,
        "asked_questions": questions,
        "answers": answers,
        "parsed_rules": parsed_rules,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "consent": consent_val,
        "session_id": session_id,
    }

    try:
        sb.table("prescreen_contacts").insert(payload).execute()
        return True, "Saved."
    except Exception as e:
        return False, f"DB error: {e}"

def is_final_decision(reply_text: str) -> bool:
    data = extract_last_json_block(reply_text)
    return bool(isinstance(data, dict) and data.get("final") is True)

def looks_like_phone(s: str) -> bool:
    """Basic phone validation: allow digits and common symbols, ensure 10–15 digits total."""
    digits = re.sub(r"\D", "", s or "")
    return 10 <= len(digits) <= 15

def normalize_phone(s: str) -> str:
    return re.sub(r"\D", "", s or "")

def looks_like_email(s: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s or ""))

def should_trigger_contact_form(text: str) -> bool:
    """
    Robust trigger: token OR common phrasing asking for email/phone/consent.
    """
    if CONTACT_TOKEN in (text or ""):
        return True
    if re.search(r"\b(email|e-mail)\b", text or "", re.I) and re.search(r"\b(phone|number)\b", text or "", re.I):
        return True
    if re.search(r"\bconsent\b", text or "", re.I) and re.search(r"\bcontact(ed)?\b", text or "", re.I):
        return True
    return False

# --- Streaming helper (streams assistant text while building full reply) ---
def stream_openai_reply(messages):
    """
    Streams assistant content to the UI and returns the full raw reply string.
    Display hides any machine JSON or CONTACT token during streaming.
    """
    with st.chat_message("assistant"):
        placeholder = st.empty()
        chunks = []
        stream = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.4,
            stream=True,
        )
        for event in stream:
            delta = getattr(event.choices[0].delta, "content", None) or ""
            if delta:
                chunks.append(delta)
                placeholder.markdown(strip_machine_json("".join(chunks)))
        full = "".join(chunks).strip()
    return full

# --- Small helper to keep viewport pinned to the bottom ---
def scroll_to_bottom():
    components.html(
        "<script>window.scrollTo(0, document.body.scrollHeight);</script>",
        height=0, width=0
    )

# =========================
# 3) STREAMLIT PAGE
# =========================
# st.title("Check Your Eligibility for Local Asthma Studies")
# st.markdown("Quickly pre-screen for a Asthma clinical trials ocurring in the Boston area. We will only contact you if you qualify.")

# Session state
if "messages" not in st.session_state:
    st.session_state.messages = []        # full history sent to model (seed hidden)
if "bootstrapped" not in st.session_state:
    st.session_state.bootstrapped = False
if "intake_complete" not in st.session_state:
    st.session_state.intake_complete = False
if "awaiting_contact" not in st.session_state:
    st.session_state.awaiting_contact = False

# =========================
# 4) SYSTEM PROMPT
# =========================
system_prompt = f"""
You are Pre-Screen PA, a clinical trial pre-screening assistant. Your job is to:
1) Parse the provided inclusion/exclusion criteria into structured rules.
2) Immediately act as if you are interviewing a patient with the fewest, most important questions (see rules below).
3) Maximize the chances of the patient answering all of your questions by keeping them engaged and occasionally positively reinforcing them if their answers make them eligible.
4) Decide: Eligible / Likely Eligible / Likely Ineligible / Unknown, with a rationale tied to exact criteria.
5) If a patient is Eligible or Likely Eligible, the UI will collect email, phone, and consent via a form. When you are ready for that step, output exactly this single token on its own line: {CONTACT_TOKEN}
6) After the form is submitted, continue with a human-readable summary and a machine-readable JSON object (see keys below). Do NOT show the JSON until after contact info is provided.

Tone & Boundaries
- Friendly, concise, clinically literate—like a trained PA. Keep the patient engaged.
- Only ask ONE question at a time, like a real conversation.
- Never give medical advice or diagnosis—only assess trial fit from provided criteria.
- Always add the disclaimer: “This is a preliminary screen based on the provided criteria; a clinician must confirm.”

Pre-Screening Efficiency Rule
- Never ask more than 5 questions total.
- Default to 3–5 highest-yield, easiest-to-answer questions.
- Stop early if ineligibility is obvious.

Operating Loop
1) Parse criteria silently.
2) Plan interview silently. Pick top 3–5 questions only.
3) Immediately begin asking questions one at a time.
4) Stop early if exclusion criteria are met.
5) When you reach your final decision and the patient is Eligible/Likely Eligible, output the token {CONTACT_TOKEN} to trigger the form (no extra text needed if you prefer).
6) AFTER the form info is provided by the user, produce:
   - Readable summary (5–10 lines)
   - Decision with rationale referencing specific criteria
   - Next steps / missing info
   - Machine-readable JSON with keys:
     decision, rationale, asked_questions, answers, missing_info, parsed_rules,
     contact_info (email, phone, consent: true/false), final: true

JSON Formatting
- Place the JSON in a single fenced block: ```json {{ ... }} ```
- Do not include any other JSON-looking code blocks.

Decision Logic
- Any exclusion met -> Likely Ineligible.
- All key inclusions met & no major exclusion -> Likely Eligible.
- Minimal/critical data missing -> Unknown.

Always include the disclaimer: “This is a preliminary screen based on the provided criteria; a clinician must confirm.”
"""

# =========================
# 5) FIRST-RUN BOOTSTRAP: seed criteria & show static greeting (NO API CALL)
# =========================
if USE_PRESET_CRITERIA and not st.session_state.bootstrapped:
    criteria_md = criteria_to_markdown(PRESET_CRITERIA)
    st.session_state.messages.append({"role": "user", "content": criteria_md, "hide": True})

    # Static greeting + first question without calling OpenAI
    greeting = (
        "Hi! I’ll ask just a few quick questions to see if you may be a fit.\n\n"
        "First up: **How old are you?**"
    )
    st.session_state.messages.append({"role": "assistant", "content": greeting})

    st.session_state.bootstrapped = True

# =========================
# 6) DISPLAY CHAT HISTORY (skip hidden seed + render snapshots nicely)
# =========================
for msg in st.session_state.messages:
    if msg.get("hide"):
        continue

    # Special renderer: a read-only snapshot of the submitted contact form
    if msg.get("type") == "contact_snapshot":
        with st.chat_message("assistant"):
            st.markdown("**Submitted contact details**")
            c = msg.get("contact", {})
            st.text_input("Email", value=c.get("email", ""), disabled=True)
            st.text_input("Phone", value=c.get("phone", ""), disabled=True)
            st.checkbox("I consent to be contacted about this study.", value=bool(c.get("consent")), disabled=True)
        continue

    # Default: regular markdown bubbles
    st.chat_message(msg["role"]).markdown(msg["content"])

# Keep viewport pinned to the bottom after rendering history
scroll_to_bottom()

# =========================
# 7) CONTACT FORM (as a function so we can render it inline when needed)
# =========================
def render_contact_form():
    with st.form("contact_form", clear_on_submit=False):
        st.markdown("**Almost done — please share your contact details:**")
        email = st.text_input("Email", placeholder="name@example.com")
        phone = st.text_input("Phone", placeholder="(555) 123-4567 or +1 555 123 4567")
        consent = st.checkbox("I consent to be contacted about this study.")
        submitted = st.form_submit_button("Submit")
        if submitted:
            errors = []
            if not looks_like_email(email):
                errors.append("Please enter a valid email.")
            if not looks_like_phone(phone):
                errors.append("Please enter a valid phone number (10–15 digits).")
            if errors:
                for e in errors:
                    st.error(e)
                return None
            return {
                "email": email.strip(),
                "phone": normalize_phone(phone),
                "consent": bool(consent),
            }
    return None

# If we were already waiting for contact info from a previous run/session, render the form now
if st.session_state.awaiting_contact:
    with st.chat_message("assistant"):
        contact = render_contact_form()
    # Keep viewport at bottom even after form render
    scroll_to_bottom()

    if contact:
        # Feed contact info to the model without showing a "sentence" bubble to the user
        contact_text = (
            "Here is my contact information from the form:\n"
            f"Email: {contact['email']}\n"
            f"Phone: {contact['phone']}\n"
            f"Consent: {'true' if contact['consent'] else 'false'}"
        )
        st.session_state.messages.append({
            "role": "user",
            "content": contact_text,
            "hide": True  # <-- keep out of visible history
        })

        # Visible, read-only snapshot of the form
        st.session_state.messages.append({
            "role": "assistant",
            "type": "contact_snapshot",
            "contact": contact,
            "content": ""
        })

        # Continue: produce final summary + JSON (hidden), then persist (streamed)
        raw_reply = stream_openai_reply(
            [{"role": "system", "content": system_prompt}] + st.session_state.messages
        )

        if is_final_decision(raw_reply):
            st.session_state.intake_complete = True
            ok, msg = persist_result(
                reply_text=raw_reply,
                session_id=st.session_state.get("_session_id")
            )
            if ok:
                st.toast("✅ Saved final decision + consent + answers to Supabase.")
            else:
                st.caption(f"Note: {msg}")

        display_reply = strip_machine_json(raw_reply)
        if display_reply:
            st.session_state.messages.append({"role": "assistant", "content": display_reply})

        st.session_state.awaiting_contact = False
        # Stop here so we don't drop into chat_input and duplicate UI
        st.stop()

# =========================
# 8) CHAT INPUT (disabled while awaiting contact form)
# =========================
if st.session_state.awaiting_contact:
    st.info("Please complete the contact form above to continue.")
else:
    placeholder = "Answer the PA's question here..."
    if user_text := st.chat_input(placeholder):
        st.session_state.messages.append({"role": "user", "content": user_text})
        st.chat_message("user").markdown(user_text)

        # STREAM the assistant reply
        raw_reply = stream_openai_reply(
            [{"role": "system", "content": system_prompt}] + st.session_state.messages
        )

        # If the model signals the form, render it immediately (no rerun) and keep at bottom
        if should_trigger_contact_form(raw_reply):
            st.session_state.awaiting_contact = True

            # Show a visible prompt if the model provided any, then the live form
            visible = strip_machine_json(raw_reply).strip()
            if not visible:
                visible = "Great—you're likely a fit. Please complete the short contact form below."
            st.session_state.messages.append({"role": "assistant", "content": visible})

            with st.chat_message("assistant"):
                contact = render_contact_form()
            scroll_to_bottom()

            if contact:
                contact_text = (
                    "Here is my contact information from the form:\n"
                    f"Email: {contact['email']}\n"
                    f"Phone: {contact['phone']}\n"
                    f"Consent: {'true' if contact['consent'] else 'false'}"
                )
                st.session_state.messages.append({
                    "role": "user",
                    "content": contact_text,
                    "hide": True
                })

                st.session_state.messages.append({
                    "role": "assistant",
                    "type": "contact_snapshot",
                    "contact": contact,
                    "content": ""
                })

                # Continue: produce final summary + JSON (hidden), then persist (streamed)
                raw_reply2 = stream_openai_reply(
                    [{"role": "system", "content": system_prompt}] + st.session_state.messages
                )

                if is_final_decision(raw_reply2):
                    st.session_state.intake_complete = True
                    ok, msg = persist_result(
                        reply_text=raw_reply2,
                        session_id=st.session_state.get("_session_id")
                    )
                    if ok:
                        st.toast("✅ Saved final decision + consent + answers to Supabase.")
                    else:
                        st.caption(f"Note: {msg}")

                display_reply2 = strip_machine_json(raw_reply2)
                if display_reply2:
                    st.session_state.messages.append({"role": "assistant", "content": display_reply2})

                st.session_state.awaiting_contact = False

            # Always stop after handling the form path to avoid duplicate UI in the same run
            st.stop()

        # Persist only on final decision (after contact form step)
        if is_final_decision(raw_reply):
            st.session_state.intake_complete = True
            ok, msg = persist_result(
                reply_text=raw_reply,
                session_id=st.session_state.get("_session_id")
            )
            if ok:
                st.toast("✅ Saved final decision + consent + answers to Supabase.")
            else:
                st.caption(f"Note: {msg}")

        display_reply = strip_machine_json(raw_reply)
        if display_reply:
            st.session_state.messages.append({"role": "assistant", "content": display_reply})

# One last nudge to keep the view pinned to the bottom after any action
scroll_to_bottom()









