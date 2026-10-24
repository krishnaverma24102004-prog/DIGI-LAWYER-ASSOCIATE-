"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import { api } from "@/lib/api";
import type { AgentStage, Analysis, ChatMessage, Citation, Consent, ServerEvent, WebSource } from "@/lib/types";

export type ConnectionStatus = "idle" | "connecting" | "connected" | "ending" | "ended" | "error";

type State = {
  status: ConnectionStatus;
  error: string | null;
  messages: ChatMessage[];
  interim: string;
  stage: AgentStage;
  stageMessage: string;
  speaking: boolean;
  voice: boolean;
  micAvailable: boolean;
  analysis: Analysis;
  citations: Citation[];
  webSources: WebSource[];
  webQueries: string[];
  notices: string[];
  transcriptId: string | null;
  // The client's consent to AI processing: until it is recorded the session keeps typed notes only.
  consentRequired: boolean;
  consent: Consent | null;
};

const initialState: State = {
  status: "idle",
  error: null,
  messages: [],
  interim: "",
  stage: "idle",
  stageMessage: "",
  speaking: false,
  voice: false,
  micAvailable: false,
  analysis: { key_facts: [], legal_issues: [], follow_up_questions: [] },
  citations: [],
  webSources: [],
  webQueries: [],
  notices: [],
  transcriptId: null,
  consentRequired: false,
  consent: null,
};

type Action =
  | { type: "connecting" }
  | { type: "mic"; available: boolean; notice?: string }
  | { type: "failed"; error: string }
  | { type: "closed" }
  | { type: "ending" }
  | { type: "server"; event: ServerEvent };

function mergeBy<T>(existing: T[], incoming: T[], key: (item: T) => string): T[] {
  const map = new Map(existing.map((item) => [key(item), item]));
  for (const item of incoming) map.set(key(item), item);
  return [...map.values()];
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "connecting":
      return { ...initialState, status: "connecting" };
    case "failed":
      return { ...state, status: "error", error: action.error, stage: "idle", speaking: false };
    case "ending":
      return { ...state, status: "ending" };
    case "mic":
      return { ...state, micAvailable: action.available, notices: action.notice ? [...state.notices, action.notice] : state.notices };
    case "closed":
      return state.status === "error" ? state : { ...state, status: "ended", stage: "idle", speaking: false };
    case "server":
      return applyEvent(state, action.event);
  }
}

function applyEvent(state: State, event: ServerEvent): State {
  switch (event.type) {
    case "session_started":
      return { ...state, status: "connected", voice: event.voice };
    case "chunk_received":
      if (event.source === "assistant") return state;
      return {
        ...state,
        interim: "",
        messages: [...state.messages, { id: `u${event.index}`, role: "user", text: event.text, redactions: event.redactions }],
      };
    case "transcript_interim":
      return { ...state, interim: event.text };
    case "agent_status":
      return { ...state, stage: event.stage, stageMessage: event.message };
    case "agent_response":
      return {
        ...state,
        messages: [
          ...state.messages,
          {
            id: `a${state.messages.length}`,
            role: "assistant",
            text: event.message,
            disclaimer: event.disclaimer_appended,
            citations: event.citations,
          },
        ],
      };
    case "agent_speaking":
      return { ...state, speaking: event.state === "start" };
    case "analysis":
      return { ...state, analysis: event.data };
    case "citations":
      return { ...state, citations: mergeBy(state.citations, event.items, (c) => c.id) };
    case "web_sources":
      return {
        ...state,
        webSources: mergeBy(state.webSources, event.items, (s) => s.url),
        webQueries: [...new Set([...state.webQueries, ...event.queries])],
      };
    case "case_memory_loaded":
      return {
        ...state,
        notices: [...state.notices, `Continuing "${event.title}": ${event.previous_sessions} earlier session(s) remembered.`],
      };
    case "practice_area_selected":
      return { ...state, notices: [...state.notices, `Practice area: ${event.name}`] };
    case "session_ended":
      return { ...state, status: "ended", transcriptId: event.transcript_id, stage: "idle", speaking: false };
    case "consent_required":
      return { ...state, consentRequired: true, consent: null };
    case "consent_status":
    case "consent_recorded":
      return { ...state, consentRequired: false, consent: event.consent };
    case "error":
      if (event.code === "consent_required") return { ...state, consentRequired: true };
      return { ...state, notices: [...state.notices, event.message] };
    default:
      return state;
  }
}

function waitForIceGathering(pc: RTCPeerConnection, timeoutMs = 3000): Promise<void> {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      pc.removeEventListener("icegatheringstatechange", check);
      resolve();
    };
    const check = () => pc.iceGatheringState === "complete" && done();
    pc.addEventListener("icegatheringstatechange", check);
    setTimeout(done, timeoutMs); // the server answers with whatever candidates we have
  });
}

export type ConnectOptions = {
  token: string;
  orgId: string | null;
  practiceAreaId: string | null;
  threadId: string | null;
  voice: boolean;
  jurisdiction: string | null;
  // Recorded at the start ("verbal" / "written"); omitted when the case thread already has it or the client said no.
  consent?: "verbal" | "written" | null;
};

/**
 * A WebRTC voice session with the agents: microphone up (hold to talk), AI voice down,
 * JSON events over a data channel.
 */
export function useVoiceSession() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const channelRef = useRef<RTCDataChannel | null>(null);
  const micRef = useRef<MediaStreamTrack | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const releaseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const teardown = useCallback(() => {
    micRef.current?.stop();
    channelRef.current?.close();
    pcRef.current?.close();
    micRef.current = channelRef.current = pcRef.current = null;
  }, []);

  useEffect(() => teardown, [teardown]);

  const send = useCallback((message: object) => {
    const channel = channelRef.current;
    if (channel?.readyState === "open") channel.send(JSON.stringify(message));
  }, []);

  const connect = useCallback(
    async ({ token, orgId, practiceAreaId, threadId, voice, jurisdiction, consent }: ConnectOptions) => {
      teardown();
      dispatch({ type: "connecting" });
      try {
        const pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
        pcRef.current = pc;
        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
          });
          const mic = stream.getAudioTracks()[0];
          mic.enabled = false; // hold to talk
          micRef.current = mic;
          pc.addTrack(mic, stream);
          dispatch({ type: "mic", available: true });
        } catch (error) {
          // No microphone (or access blocked): typing still works, and replies can still be heard.
          pc.addTransceiver("audio", { direction: "recvonly" });
          const blocked = error instanceof DOMException && error.name === "NotAllowedError";
          dispatch({
            type: "mic",
            available: false,
            notice: blocked ? "Microphone access is blocked; you can type instead." : "No microphone found; you can type instead.",
          });
        }

        const channel = pc.createDataChannel("events");
        channelRef.current = channel;
        channel.onmessage = (e) => dispatch({ type: "server", event: JSON.parse(e.data) as ServerEvent });
        channel.onclose = () => dispatch({ type: "closed" });

        pc.ontrack = (e) => {
          const audio = audioRef.current;
          if (!audio) return;
          audio.srcObject = e.streams[0] ?? new MediaStream([e.track]);
          audio.play().catch(() => undefined);
        };
        pc.onconnectionstatechange = () => {
          if (pc.connectionState === "failed") dispatch({ type: "failed", error: "The voice connection failed (network or firewall)." });
        };

        await pc.setLocalDescription(await pc.createOffer());
        await waitForIceGathering(pc);
        const answer = await api<{ sdp: string; type: RTCSdpType }>("/api/v1/webrtc/offer", {
          token,
          orgId,
          method: "POST",
          body: {
            sdp: pc.localDescription?.sdp,
            type: "offer",
            org_id: orgId,
            practice_area_id: practiceAreaId,
            thread_id: threadId,
            mode: "conversation",
            voice,
            jurisdiction,
            consent: consent ?? null,
          },
        });
        await pc.setRemoteDescription(answer);
      } catch (error) {
        teardown();
        dispatch({ type: "failed", error: error instanceof Error ? error.message : String(error) });
      }
    },
    [teardown],
  );

  const sendText = useCallback((text: string) => send({ type: "transcript_chunk", speaker: "User", text }), [send]);

  const startTalking = useCallback(() => {
    if (releaseTimer.current) clearTimeout(releaseTimer.current);
    if (micRef.current) micRef.current.enabled = true;
    send({ type: "ptt", state: "start" }); // also stops the AI if it is speaking
  }, [send]);

  const stopTalking = useCallback(() => {
    // Keep the mic open a moment so the last syllable isn't clipped.
    releaseTimer.current = setTimeout(() => {
      if (micRef.current) micRef.current.enabled = false;
      send({ type: "ptt", state: "stop" });
    }, 300);
  }, [send]);

  const interrupt = useCallback(() => send({ type: "interrupt" }), [send]);

  const recordConsent = useCallback((method: "verbal" | "written") => send({ type: "consent", method }), [send]);

  const end = useCallback(() => {
    dispatch({ type: "ending" });
    send({ type: "end" });
    // The server summarizes and saves, replies session_ended, then closes the channel.
    setTimeout(teardown, 30000);
  }, [send, teardown]);

  return { state, audioRef, connect, sendText, startTalking, stopTalking, interrupt, recordConsent, end, disconnect: teardown };
}
