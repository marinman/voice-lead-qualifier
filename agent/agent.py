"""Voice SDR agent: discloses itself, asks five qualification questions, answers
FAQ-only product questions, then scores and routes the visitor.

Run:
    .venv/bin/python agent/agent.py download-files   # once, fetches VAD + turn detector
    .venv/bin/python agent/agent.py dev
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livekit.agents import (  # noqa: E402
    Agent, AgentServer, AgentSession, CloseEvent, JobContext, JobProcess, RunContext,
    UserStateChangedEvent, cli, function_tool, inference,
)
from livekit.plugins import silero  # noqa: E402

from qualifier import faq, guardrails, storage  # noqa: E402
from qualifier.config import AGENT_NAME, DISCLOSURE, OUT_OF_SCOPE, QUESTIONS  # noqa: E402
from qualifier.pipeline import finalize  # noqa: E402

log = logging.getLogger("lead-qualifier")

STT = os.environ.get("AGENT_STT", "deepgram/nova-3:en")
LLM = os.environ.get("AGENT_LLM", "openai/gpt-4.1-mini")
TTS = os.environ.get("AGENT_TTS", "cartesia/sonic-3:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc")
SILENCE_SECONDS = float(os.environ.get("SILENCE_SECONDS", "10"))
RESULT_TOPIC = "lead_result"
# "inference" (default): LiveKit Inference, billed to your LiveKit Cloud project.
# "openai": OpenAI plugins with OPENAI_API_KEY, e.g. for a self-hosted LiveKit server.
PROVIDER = os.environ.get("AGENT_PROVIDER", "inference")


def build_models() -> dict:
    if PROVIDER == "openai":
        from livekit.plugins import openai

        return {
            "stt": openai.STT(model=os.environ.get("OPENAI_STT_MODEL", "gpt-4o-transcribe")),
            "llm": openai.LLM(model=os.environ.get("OPENAI_LLM_MODEL", "gpt-4.1-mini")),
            "tts": openai.TTS(model=os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"), voice="alloy"),
            "turn_detection": "vad",
        }
    return {"stt": STT, "llm": LLM, "tts": TTS, "turn_detection": inference.TurnDetector()}


def build_instructions() -> str:
    questions = "\n".join(f"Q{i + 1}. {q}" for i, (_, q) in enumerate(QUESTIONS))
    return f"""You are a friendly, concise SDR voice assistant on the landing page for the
"Voice AI Readiness Assessment". You are speaking out loud: short sentences, no lists,
no markdown, no emojis.

You already opened with this disclosure and Q1: "{DISCLOSURE}"

Ask these five questions, one at a time, in order. After each answer, confirm it in a
few words (e.g. "Got it, about 600 people.") before asking the next. If an answer is
vague, ask one short clarifying follow-up at most, then move on.
{questions}

Product questions: answer ONLY from the FAQ below, in one or two sentences, then return
to the next unanswered question. For anything not covered by the FAQ, say exactly:
"{OUT_OF_SCOPE}" and continue. Never invent pricing, features, or commitments.

FAQ:
{faq.prompt_block()}

When all five questions are answered (or the visitor declines to answer the rest),
call the `finish_qualification` tool. Then say the closing line the tool gives you,
thank them, and stop. No hard sell.

If the visitor asks to stop, end, or says they are not interested, call `stop_call`
immediately without asking anything else."""


class CallState:
    def __init__(self, ctx: JobContext, utm: dict):
        self.ctx = ctx
        self.utm = utm
        self.started = time.time()
        self.conversation_id: str | None = None
        self.away_prompted = False
        self.ending = False


def transcript_of(session: AgentSession) -> list[dict]:
    out = []
    for item in session.history.items:
        if getattr(item, "type", None) == "message" and item.role in ("user", "assistant"):
            text = (item.text_content or "").strip()
            if text:
                out.append({"role": item.role, "text": text})
    return out


async def finalize_call(state: CallState, session: AgentSession, end_reason: str) -> dict | None:
    """Extract, score, persist, and push the result card to the browser. Idempotent."""
    if state.conversation_id:
        return None
    result = await asyncio.to_thread(
        finalize,
        transcript_of(session),
        channel="voice",
        utm=state.utm,
        duration_seconds=int(time.time() - state.started),
        room_name=state.ctx.room.name,
        end_reason=end_reason,
    )
    state.conversation_id = result["id"]
    try:
        await state.ctx.room.local_participant.send_text(json.dumps(result), topic=RESULT_TOPIC)
    except Exception:
        log.exception("could not push result to browser (it will poll instead)")
    return result


def shutdown_after_reply(ctx: RunContext) -> None:
    # For a non-realtime LLM the tool reply reuses this speech handle, so closing
    # when it finishes lets the agent finish its closing line first.
    ctx.speech_handle.add_done_callback(lambda _: ctx.session.shutdown())


class Qualifier(Agent):
    def __init__(self, state: CallState):
        super().__init__(instructions=build_instructions())
        self.state = state

    async def on_enter(self) -> None:
        await self.session.say(f"{DISCLOSURE} {QUESTIONS[0][1]}")

    @function_tool
    async def finish_qualification(self, context: RunContext) -> str:
        """Call once all five qualification questions are answered or declined.
        Scores the conversation and returns the closing line to say."""
        self.state.ending = True
        result = await finalize_call(self.state, context.session, "completed")
        shutdown_after_reply(context)
        line = (result or {}).get("next_step", {}).get("agent_line", "Thanks for your time.")
        return f'Say this closing line naturally, then a brief thank-you, and nothing else: "{line}"'

    @function_tool
    async def stop_call(self, context: RunContext) -> str:
        """Call immediately when the visitor asks to stop, end the call, or says they are not interested."""
        self.state.ending = True
        await finalize_call(self.state, context.session, "visitor_stopped")
        shutdown_after_reply(context)
        return 'Say only: "No problem, ending here. Thanks for your time."'


# One small VM hosts web + agent, so keep warm worker processes low
# (the framework's production default is 12).
server = AgentServer(num_idle_processes=int(os.environ.get("AGENT_IDLE_PROCESSES", "1")))


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    try:
        utm = json.loads(ctx.job.metadata or "{}")
    except json.JSONDecodeError:
        utm = {}
    state = CallState(ctx, utm)

    session = AgentSession(
        **build_models(),
        vad=ctx.proc.userdata["vad"],
        user_away_timeout=SILENCE_SECONDS,
    )

    @session.on("user_state_changed")
    def _on_user_state(ev: UserStateChangedEvent) -> None:
        if ev.new_state == "speaking":
            state.away_prompted = False
        if ev.new_state != "away" or state.ending:
            return
        if not state.away_prompted:
            state.away_prompted = True
            session.generate_reply(
                instructions="The visitor has been silent. Briefly ask if they're still there, once."
            )
        else:
            state.ending = True

            async def _wrap() -> None:
                await finalize_call(state, session, "silence")
                handle = session.say("Looks like we got disconnected. I'll leave some resources on your screen. Bye for now.")
                await handle
                session.shutdown()

            asyncio.create_task(_wrap())

    @session.on("close")
    def _on_close(ev: CloseEvent) -> None:
        async def _save() -> None:
            # Visitor hung up before finishing: save the partial record.
            await finalize_call(state, session, "disconnected")
            # Store the full transcript, including the closing line spoken after scoring.
            await asyncio.to_thread(
                storage.update_transcript, state.conversation_id, transcript_of(session),
                int(time.time() - state.started),
            )

        async def _shutdown_cb() -> None:
            await _save()
            await ctx.delete_room()

        ctx.add_shutdown_callback(_shutdown_cb)
        ctx.shutdown(reason=ev.reason.value if ev.reason else "closed")

    await session.start(agent=Qualifier(state), room=ctx.room)

    # Hard cap on call length (public demo link): wrap up and save what we have.
    async def _time_limit() -> None:
        await asyncio.sleep(guardrails.max_session_seconds())
        if state.ending:
            return
        state.ending = True
        await finalize_call(state, session, "time_limit")
        await session.say("We've hit the time limit for this demo, so I'll wrap up here. Your next step is on screen. Thanks!")
        session.shutdown()

    timer = asyncio.create_task(_time_limit())

    async def _cancel_timer() -> None:
        timer.cancel()

    ctx.add_shutdown_callback(_cancel_timer)


if __name__ == "__main__":
    cli.run_app(server)
