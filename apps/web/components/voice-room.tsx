"use client";
import { useEffect, useRef, useState } from "react";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useRoomContext,
  useConnectionState,
  useLocalParticipant,
  BarVisualizer,
  useVoiceAssistant,
} from "@livekit/components-react";
import {
  ConnectionState,
  RoomEvent,
  Track,
  createLocalAudioTrack,
  type RemoteTrack,
  type LocalTrackPublication,
} from "livekit-client";
import { Mic, MicOff, PhoneOff, Headphones } from "lucide-react";
import { api, type Connection } from "@/lib/api";

function Controls({
  connection,
  onEnd,
  staff,
}: {
  connection: Connection;
  onEnd: () => void;
  staff: boolean;
}) {
  const room = useRoomContext();
  const state = useConnectionState();
  const { localParticipant, isMicrophoneEnabled } = useLocalParticipant();
  const { state: agentState, audioTrack } = useVoiceAssistant();
  const [error, setError] = useState("");
  const [staffReady, setStaffReady] = useState(!staff);
  const readyRef = useRef(false);
  useEffect(() => {
    if (!staff || state !== ConnectionState.Connected || readyRef.current)
      return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const detail = await api<{ call: { status: string } }>(
          `/calls/${connection.call.id}`,
        );
        if (detail.call.status === "human_active" && !cancelled) {
          readyRef.current = true;
          setStaffReady(true);
          clearInterval(timer);
        }
      } catch {
        /* Keep microphone gated until backend confirms takeover. */
      }
    }, 500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [staff, state, connection.call.id]);
  useEffect(() => {
    if (!staff || state !== ConnectionState.Connected) return;
    let cancelled = false;
    const existing = localParticipant.getTrackPublication(
      Track.Source.Microphone,
    )?.track;
    if (existing) return;
    createLocalAudioTrack()
      .then(async (track) => {
        if (cancelled) {
          track.stop();
          return;
        }
        // Disable capture before publication; never leak staff speech into the AI turn.
        track.mediaStreamTrack.enabled = readyRef.current;
        await localParticipant.publishTrack(track);
        track.mediaStreamTrack.enabled = readyRef.current;
      })
      .catch((e) => setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [staff, state, localParticipant]);
  useEffect(() => {
    if (staff) {
      const track = localParticipant.getTrackPublication(
        Track.Source.Microphone,
      )?.track;
      if (track) track.mediaStreamTrack.enabled = staffReady;
    }
  }, [staff, staffReady, localParticipant]);
  return (
    <div className="voice-active">
      <div className="voice-orb">
        <BarVisualizer
          state={agentState}
          barCount={7}
          trackRef={audioTrack}
          options={{ minHeight: 8 }}
        />
      </div>
      <div className="connection-line">
        <span
          className={`status-dot ${state === ConnectionState.Connected ? "live" : ""}`}
        />
        {state === ConnectionState.Connected
          ? staff
            ? staffReady
              ? "Human support connected"
              : "Connecting takeover…"
            : agentState === "speaking"
              ? "Mira is speaking"
              : agentState === "thinking"
                ? "Checking that for you…"
                : "Listening to you…"
          : state}
      </div>
      <p className="muted small">
        {staff
          ? "Your microphone opens after AI audio stops."
          : "Speak naturally. You can interrupt at any time."}
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="call-buttons">
        <button
          className="icon-button"
          aria-label={
            isMicrophoneEnabled ? "Mute microphone" : "Unmute microphone"
          }
          disabled={staff && !staffReady}
          onClick={() =>
            localParticipant
              .setMicrophoneEnabled(!isMicrophoneEnabled)
              .catch((e) => setError(e.message))
          }
        >
          {isMicrophoneEnabled ? <Mic size={19} /> : <MicOff size={19} />}
        </button>
        <button className="end-call" onClick={onEnd}>
          <PhoneOff size={18} /> {staff ? "Leave room" : "End call"}
        </button>
      </div>
    </div>
  );
}

function AudioMeasurement({ callId }: { callId: string }) {
  const room = useRoomContext();
  useEffect(() => {
    let disposed = false;
    const context = new AudioContext();
    const sources: AudioNode[] = [];
    let raf = 0,
      lastUserEnergy = 0,
      userActive = false,
      lastRemoteEnergy = 0,
      remoteActive = false,
      awaitingResponse = false,
      interruptStart = 0;
    const local = room.localParticipant.getTrackPublication(
      Track.Source.Microphone,
    )?.track;
    const analysers: { analyser: AnalyserNode; local: boolean }[] = [];
    function attach(track: MediaStreamTrack, isLocal: boolean) {
      const source = context.createMediaStreamSource(new MediaStream([track]));
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      sources.push(source);
      analysers.push({ analyser, local: isLocal });
    }
    if (local) attach(local.mediaStreamTrack, true);
    function subscribed(track: RemoteTrack) {
      if (track.kind === Track.Kind.Audio)
        attach(track.mediaStreamTrack, false);
    }
    room.remoteParticipants.forEach((p) =>
      p.trackPublications.forEach((pub) => {
        if (pub.track?.kind === Track.Kind.Audio)
          attach(pub.track.mediaStreamTrack, false);
      }),
    );
    function localPublished(publication: LocalTrackPublication) {
      if (publication.track?.kind === Track.Kind.Audio)
        attach(publication.track.mediaStreamTrack, true);
    }
    room.on(RoomEvent.TrackSubscribed, subscribed);
    room.on(RoomEvent.LocalTrackPublished, localPublished);
    const post = (name: string, value: number) =>
      api(`/calls/${callId}/metrics`, "POST", {
        name,
        value,
        tags: { tool_turn: "unknown" },
      }).catch(() => {});
    function frame() {
      if (disposed) return;
      const now = performance.now();
      let localLoud = false,
        remoteLoud = false;
      for (const { analyser, local } of analysers) {
        const samples = new Float32Array(analyser.fftSize);
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(
          samples.reduce((s, v) => s + v * v, 0) / samples.length,
        );
        if (rms > 0.025) {
          if (local) localLoud = true;
          else remoteLoud = true;
        }
      }
      if (localLoud) {
        if (!userActive && remoteActive) interruptStart = now;
        userActive = true;
        lastUserEnergy = now;
        awaitingResponse = true;
      }
      if (userActive && now - lastUserEnergy > 350) userActive = false;
      if (remoteLoud) {
        if (
          !remoteActive &&
          awaitingResponse &&
          !userActive &&
          lastUserEnergy
        ) {
          post("audio_response_seconds", (now - lastUserEnergy) / 1000);
          awaitingResponse = false;
        }
        remoteActive = true;
        lastRemoteEnergy = now;
      }
      if (remoteActive && now - lastRemoteEnergy > 180) {
        remoteActive = false;
        if (interruptStart) {
          post(
            "audio_interruption_seconds",
            Math.max(0, (lastRemoteEnergy - interruptStart) / 1000),
          );
          interruptStart = 0;
        }
      }
      raf = requestAnimationFrame(frame);
    }
    context.resume().catch(() => {});
    raf = requestAnimationFrame(frame);
    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      sources.forEach((s) => s.disconnect());
      room.off(RoomEvent.TrackSubscribed, subscribed);
      room.off(RoomEvent.LocalTrackPublished, localPublished);
      context.close();
    };
  }, [room, callId]);
  return null;
}
export default function VoiceRoom({
  connection,
  onEnd,
  staff = false,
}: {
  connection: Connection;
  onEnd: () => void;
  staff?: boolean;
}) {
  const [error, setError] = useState("");
  return (
    <div className="room-shell">
      {error && (
        <div role="alert" className="error">
          {error} <button onClick={onEnd}>Close call</button>
        </div>
      )}
      <LiveKitRoom
        token={connection.token}
        serverUrl={connection.url}
        connect
        audio={!staff}
        video={false}
        onError={(e) =>
          setError(
            e.message.includes("Permission")
              ? "Microphone access was denied. Allow microphone access in your browser and retry."
              : e.message,
          )
        }
        onDisconnected={() =>
          setError(
            "Disconnected. Close this call, or reconnect from the escalation queue.",
          )
        }
      >
        <RoomAudioRenderer />
        <Controls connection={connection} onEnd={onEnd} staff={staff} />
        {!staff && <AudioMeasurement callId={connection.call.id} />}
      </LiveKitRoom>
      <div className="small muted room-footer">
        <Headphones size={13} /> Headphones recommended
      </div>
    </div>
  );
}
