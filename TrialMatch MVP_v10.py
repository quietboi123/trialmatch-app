# -*- coding: utf-8 -*-
"""
TrialMatch Recruiter (v8, preset criteria, hidden JSON, contact FORM-as-CARD, widget-key fix)
"""

import streamlit as st
from openai import OpenAI
from supabase import create_client, Client
import json
import re
from datetime import datetime, timezone

# =========================
# 0) CONFIG
# =========================
USE_PRESET_CRITERIA = True
CONTACT_TOKEN = "[CONTACT_INFO_FORM]"

PRESET_CRITERIA = {
    "title": "MDD / TRD Outpatient Study (Example)",
    "inclusion": [
        "Participant is ≥ 18 years old",
        "Primary diagnosis of recurrent MDD (moderate or severe) OR persistent depressive disorder",
        "Inadequate response to oral antidepressants in the current episode",
        "On a stable oral antidepressant regimen for ≥ 8 weeks prior to screening",
        "Willing and able to comply with all study procedures and restrictions"
    ],
    "exclusion": [
        "Primary focus of treatment in the last 12 months is a psychiatric disorder other than MDD",
        "Considered by the investigator to be at imminent risk of suicide or self-harm"
    ],
}

def criteria_to_markdown(criteria: dict) -> str:
    inc = "\n".join(f"* {item}" for item in criteria.get("inclusion", []))
    exc = "\n".join(f"* {item}" for item in criteria.get("exclusion", []))
    title = criteria.get("title", "Trial Criteria")
    return f"**{title}**\n\n**Key Inclusion Criteria:**\n{inc}\n\n**Key Exclusion Criteria:**\n{exc}"

# =========================
# 1) CLIENTS
# =========================
client = OpenAI(api_key=st.secrets["openai"]["api_key"])

def get_supabase() -> Client:
    return create_client(
        st.secrets["supabase"]["url"],
        st.secrets["supabase"]["service_key"]
    )

# =========================
# 2) HELPERS
# =========================
def _as_bool(value) -> bool:
    if isinstance(value, bool): return value
    if isinstance(value, (int, float)): return value != 0
    if isinstance(value, str): return value.strip().lower() in {"yes","y","true","t","1","consent","agree","agreed"}
    return False

def _normalize_decision(s: str) -> str:
    s = (s or "").strip().lower()
    if "likely ineligible" in s or "ineligible" in s: return "Likely Ineligible"
    if "likely eligible" in s: return "Likely Eligible"
    if s == "eligible" or ("eligible" in s and "likely" not in s and "ineligible" not in s): return "Eligible"
    if "unknown" in s: return "Unknown"
    return "Unknown"

def extract_last_json_block(text: str):
    try:
        blocks = re.findall(r"```(?:json)?\s*({[\s\S]*?})\s*```", text)
        candidate = blocks[-1] if blocks else re.findall(r"({[\s\S]*})", text)[-1]
        return json.loads(candidate)
    except Exception:
        return None

def strip_machine_json(text: str) -> str:
    t = re.sub(r"```(?:json)?\s*{[\s\S]*?}\s*```", "", text or "").strip()
    t = re.sub(r"\s*{[\s\S]*}\s*$", "", t).strip()
    return t.replace(CONTACT_TOKEN, "").strip()

def persist_result(reply_text: str, session_id: str = None):
    sb = get_supabase()
    data = extract_last_json_block(reply_text)

    decision, rationale, answers, parsed_rules = "Unknown", "No JSON payload found.", None, None
    contact, trial_title, questions = {}, None, None
    if data:
        decision = _normalize_decision(data.get("decision"))
        rationale = data.get("rationale")
        answers = data.get("answers")
        parsed_rules = data.get("parsed_rules")
        contact = data.get("contact_info") or {}
        trial_title = (parsed_rules or {}).get("trial_title")
        questions = data.get("asked_questions")

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trial_title": trial_title,
        "decision": decision,
        "rationale": rationale,
        "asked_questions": questions,
        "answers": answers,
        "parsed_rules": parsed_rules,
        "contact_email": contact.get("email"),
        "contact_phone": contact.get("phone"),
        "consent": _as_bool(contact.get("consent")),
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
    digits = re.sub(r"\D", "", s or "")
    return 10 <= len(digits) <= 15

def normalize_phone(s: str) -> str:
    return re.sub(r"\D", "", s or "")

def looks_like_email(s: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s or ""))

def should_trigger_contact_form(text: str) -> bool:
    if CONTACT_TOKEN in (text or ""): return True
    if re.search(r"\b(email|e-mail)\b", text or "", re.I) and re.search(r"\b(phone|number)\b", text or "", re.I): return True
    if re.search(r"\bconsent\b", text or "", re.I) and re.search(r"\bcontact(ed)?\b", text or "", re.I): return True
    return False

# ----- UI helpers -----
def render_contact_card(contact: dict, card_id: int):
    """Draw a read-only 'form' card inside an assistant bubble with UNIQUE KEYS."""
    with st.chat_message("assistant"):
        st.markdown("**Contact details submitted**")
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Email", value=contact.get("email", ""), disabled=True, key=f"card_email_{card_id}")
        with c2:
            phone_display = contact.get("raw_phone") or contact.get("phone", "")
            st.text_input("Phone", value=phone_display, disabled=True, key=f"card_phone_{card_id}")
        st.checkbox(
            "I consent to be contacted about this study.",
            value=bool(contact.get("consent")),
            disabled=True,
            key=f"card_consent_{card_id}"
        )

# =========================
# 3) STREAMLIT PAGE
# =========================
st.set_page_config(page_title="TrialMatch Recruiter", page_icon="🧪")
st.title("🧪 TrialMatch Recruiter")
st.markdown("Chat with a friendly assistant to quickly pre-screen for clinical trials.")

# Session state
ss = st.session_state
if "messages" not in ss: ss.messages = []
if "bootstrapped" not in ss: ss.bootstrapped = False
if "intake_complete" not in ss: ss.intake_complete = False
if "awaiting_contact" not in ss: ss.awaiting_contact = False
if "contact_card_counter" not in ss: ss.contact_card_counter = 0  # for unique widget keys

# =========================
# 4) SYSTEM PROMPT
# =========================
system_prompt = f"""
You are Pre-Screen PA, a clinical trial pre-screening assistant...
When you are ready to collect contact info, output exactly this token on its own line: {CONTACT_TOKEN}
After the form is submitted, produce the human summary + single fenced JSON object (do not include the JSON in earlier turns).
"""

# (Full prompt omitted here for brevity; use the same content you had previously.)
# If you want the complete long prompt back in, paste the prior version unchanged except for the token line above.

# =========================
# 5) FIRST-RUN BOOTSTRAP
# =========================
if USE_PRESET_CRITERIA and not ss.bootstrapped:
    criteria_md = criteria_to_markdown(PRESET_CRITERIA)
    ss.messages.append({"role": "user", "content": criteria_md, "hide": True})
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": system_prompt}] + ss.messages,
            temperature=0.4,
        )
        first_raw = response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"Model error during bootstrap: {e}")
        st.stop()

    if should_trigger_contact_form(first_raw):
        ss.awaiting_contact = True
        ss.messages.append({"role": "assistant", "content": "Great—based on your answers, you're likely a fit. Please complete the short contact form below."})
        st.rerun()

    first_display = strip_machine_json(first_raw) or "Thanks. Let's get started—I'll ask a few quick questions."
    ss.messages.append({"role": "assistant", "content": first_display})
    ss.bootstrapped = True

# =========================
# 6) DISPLAY HISTORY (cards + normal bubbles)
# =========================
for i, msg in enumerate(ss.messages):
    if msg.get("hide"):  # hidden seed/model-bridge turns
        continue
    if msg.get("type") == "contact_card":
        render_contact_card(msg.get("data", {}), msg.get("card_id", i))
    else:
        st.chat_message(msg["role"]).markdown(msg["content"])

# =========================
# 7) CONTACT FORM (only when requested)
# =========================
def render_contact_form():
    with st.form("contact_form", clear_on_submit=False):
        st.markdown("**Almost done — please share your contact details:**")
        email = st.text_input("Email", placeholder="name@example.com", key="form_email")
        phone = st.text_input("Phone", placeholder="(555) 123-4567 or +1 555 123 4567", key="form_phone")
        consent = st.checkbox("I consent to be contacted about this study.", key="form_consent")
        submitted = st.form_submit_button("Submit", use_container_width=True)
        if submitted:
            errors = []
            if not looks_like_email(email): errors.append("Please enter a valid email.")
            if not looks_like_phone(phone): errors.append("Please enter a valid phone number (10–15 digits).")
            if errors:
                for e in errors: st.error(e)
                return None
            return {"email": email.strip(), "phone": normalize_phone(phone), "raw_phone": phone.strip(), "consent": bool(consent)}
    return None

if ss.awaiting_contact:
    contact = render_contact_form()
    if contact:
        # Hidden turn to the model
        contact_text = (
            "Here is my contact information from the form:\n"
            f"Email: {contact['email']}\n"
            f"Phone: {contact['phone']}\n"
            f"Consent: {'true' if contact['consent'] else 'false'}"
        )
        ss.messages.append({"role": "user", "content": contact_text, "hide": True})

        # Visible read-only card with UNIQUE widget keys
        ss.contact_card_counter += 1
        ss.messages.append({
            "role": "assistant", "type": "contact_card",
            "data": contact, "card_id": ss.contact_card_counter
        })

        # Ask model to produce final summary + JSON (JSON stays hidden in UI)
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "system", "content": system_prompt}] + ss.messages,
                temperature=0.4,
            )
            raw_reply = response.choices[0].message.content.strip()
        except Exception as e:
            st.error(f"Model error after contact: {e}")
            st.stop()

        if is_final_decision(raw_reply):
            ss.intake_complete = True
            ok, msg = persist_result(reply_text=raw_reply, session_id=ss.get("_session_id"))
            if ok: st.toast("✅ Saved final decision + consent + answers to Supabase.")
            else:  st.caption(f"Note: {msg}")

        display_reply = strip_machine_json(raw_reply)
        ss.messages.append({"role": "assistant", "content": display_reply})

        ss.awaiting_contact = False
        st.rerun()

# =========================
# 8) CHAT INPUT
# =========================
if ss.awaiting_contact:
    st.info("Please complete the contact form above to continue.")
else:
    placeholder = "Answer the PA's question here..."
    if user_text := st.chat_input(placeholder):
        ss.messages.append({"role": "user", "content": user_text})
        st.chat_message("user").markdown(user_text)

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "system", "content": system_prompt}] + ss.messages,
                temperature=0.4,
            )
            raw_reply = response.choices[0].message.content.strip()
        except Exception as e:
            st.error(f"Model error: {e}")
            st.stop()

        # Trigger form immediately if needed
        if should_trigger_contact_form(raw_reply):
            ss.awaiting_contact = True
            visible = strip_machine_json(raw_reply).strip() or "Great—you're likely a fit. Please complete the short contact form below."
            ss.messages.append({"role": "assistant", "content": visible})
            st.rerun()

        # Persist only on final decision (after contact step)
        if is_final_decision(raw_reply):
            ss.intake_complete = True
            ok, msg = persist_result(reply_text=raw_reply, session_id=ss.get("_session_id"))
            if ok: st.toast("✅ Saved final decision + consent + answers to Supabase.")
            else:  st.caption(f"Note: {msg}")

        display_reply = strip_machine_json(raw_reply)
        if display_reply:
            ss.messages.append({"role": "assistant", "content": display_reply})
            st.chat_message("assistant").markdown(display_reply)
