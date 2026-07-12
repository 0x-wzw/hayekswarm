"use client";

import { useEffect, useState, useRef, useCallback } from "react";

// ── Types ──────────────────────────────────────────────────────

interface ChatMessage {
  message_id: string;
  session_id: string;
  role: "user" | "agent" | "system" | "human_gate";
  sender: string;
  sender_name: string;
  content: string;
  metadata: Record<string, unknown>;
  timestamp: string;
  protocol: string;
  task_id: string;
  requires_approval: boolean;
  approved: boolean | null;
}

interface Session {
  session_id: string;
  title: string;
  status: "active" | "paused" | "completed" | "archived";
  participants: string[];
  human_in_loop: boolean;
  created_at: string;
  updated_at: string;
  messages: ChatMessage[];
  turn_policy: string;
  max_turns: number;
  current_turn: number;
}

interface Agent {
  tether_id: string;
  name: string;
  origin_protocol: string;
  capabilities: {
    tasks?: string[];
    modalities?: string[];
    streaming?: boolean;
  };
}

// ── Agent color map ────────────────────────────────────────────

const AGENT_COLORS: Record<string, string> = {
  a2a: "border-blue-400 bg-blue-950/40",
  mcp: "border-green-400 bg-green-950/40",
  hermes: "border-purple-400 bg-purple-950/40",
  swarm: "border-yellow-400 bg-yellow-950/40",
  crewai: "border-red-400 bg-red-950/40",
  langgraph: "border-cyan-400 bg-cyan-950/40",
  openclaw: "border-orange-400 bg-orange-950/40",
  custom: "border-gray-400 bg-gray-950/40",
  user: "border-emerald-400 bg-emerald-950/40",
  system: "border-zinc-500 bg-zinc-900/40",
};

const AGENT_AVATARS: Record<string, string> = {
  a2a: "🔵",
  mcp: "🟢",
  hermes: "🟣",
  swarm: "🟡",
  crewai: "🔴",
  langgraph: "🔵",
  openclaw: "🟠",
  custom: "⚪",
  user: "👤",
  system: "⚫",
};

function getAgentColor(sender: string, protocol: string): string {
  if (sender === "user") return AGENT_COLORS.user;
  if (sender === "system") return AGENT_COLORS.system;
  return AGENT_COLORS[protocol] || AGENT_COLORS.custom;
}

function getAgentAvatar(sender: string, protocol: string): string {
  if (sender === "user") return AGENT_AVATARS.user;
  if (sender === "system") return AGENT_AVATARS.system;
  return AGENT_AVATARS[protocol] || AGENT_AVATARS.custom;
}

// ── API URL ────────────────────────────────────────────────────

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8901";
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || `ws://localhost:8901`;

// ── Components ─────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const color = getAgentColor(msg.sender, msg.protocol);
  const avatar = getAgentAvatar(msg.sender, msg.protocol);
  const time = new Date(msg.timestamp).toLocaleTimeString();

  return (
    <div className={`flex gap-3 p-3 rounded-lg border ${color}`}>
      <div className="text-2xl flex-shrink-0">{avatar}</div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="font-bold text-sm text-zinc-100">
            {msg.sender_name || msg.sender}
          </span>
          <span className="text-xs text-zinc-500">
            {msg.protocol && msg.protocol !== "" ? `[${msg.protocol}]` : ""}
          </span>
          <span className="text-xs text-zinc-600 ml-auto">{time}</span>
        </div>
        <div className="text-sm text-zinc-200 whitespace-pre-wrap break-words">
          {msg.content}
        </div>
        {msg.requires_approval && msg.approved === null && (
          <div className="mt-2 flex gap-2">
            <button className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white text-xs rounded">
              ✓ Approve
            </button>
            <button className="px-3 py-1 bg-red-600 hover:bg-red-500 text-white text-xs rounded">
              ✗ Reject
            </button>
          </div>
        )}
        {msg.approved === true && (
          <span className="text-xs text-emerald-400">✓ Approved</span>
        )}
        {msg.approved === false && (
          <span className="text-xs text-red-400">✗ Rejected</span>
        )}
      </div>
    </div>
  );
}

function AgentCard({ agent }: { agent: Agent }) {
  const color = AGENT_COLORS[agent.origin_protocol] || AGENT_COLORS.custom;
  const avatar = AGENT_AVATARS[agent.origin_protocol] || AGENT_AVATARS.custom;
  const tasks = agent.capabilities?.tasks || [];

  return (
    <div className={`p-3 rounded-lg border ${color}`}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xl">{avatar}</span>
        <span className="font-bold text-sm text-zinc-100">{agent.name}</span>
      </div>
      <div className="text-xs text-zinc-400 mb-2">{agent.tether_id}</div>
      <div className="flex flex-wrap gap-1">
        {(tasks || []).map((t: string) => (
          <span
            key={t}
            className="px-1.5 py-0.5 text-[10px] bg-zinc-800 text-zinc-300 rounded"
          >
            {t}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────

export default function VoidTetherUI() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSession, setCurrentSession] = useState<Session | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [inputMessage, setInputMessage] = useState("");
  const [wsConnected, setWsConnected] = useState(false);
  const [eventLog, setEventLog] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // ── API calls ──────────────────────────────────────────

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/sessions`);
      const data = await res.json();
      setSessions(data);
    } catch {
      // Server not available yet
    }
  }, []);

  const fetchAgents = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/agents`);
      const data = await res.json();
      setAgents(data);
    } catch {
      // Server not available yet
    }
  }, []);

  const createSession = async () => {
    const participantIds = agents.map((a) => a.tether_id);
    const res = await fetch(`${API}/api/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: `Session ${sessions.length + 1}`,
        participants: participantIds,
        human_in_loop: true,
        turn_policy: "round_robin",
      }),
    });
    const session = await res.json();
    setCurrentSession(session);
    setSessions((prev) => [...prev, session]);
    connectWS(session.session_id);
  };

  const sendMessage = async () => {
    if (!inputMessage.trim() || !currentSession) return;

    await fetch(`${API}/api/sessions/${currentSession.session_id}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sender: "user",
        sender_name: "User",
        content: inputMessage,
        role: "user",
      }),
    });

    setInputMessage("");
  };

  const connectWS = (sessionId: string) => {
    if (wsRef.current) wsRef.current.close();
    const ws = new WebSocket(`${WS_URL}/ws/${sessionId}`);
    ws.onopen = () => setWsConnected(true);
    ws.onclose = () => setWsConnected(false);
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "session_history") {
          setCurrentSession(data.session);
        } else {
          // Update messages in current session
          setEventLog((prev) => [
            `[${new Date().toLocaleTimeString()}] ${data.event_type}: ${data.content?.substring(0, 80)}`,
            ...prev.slice(0, 49),
          ]);
          // Refetch session to get new messages
          fetch(
            `${API}/api/sessions/${sessionId}`
          )
            .then((r) => r.json())
            .then((s) => setCurrentSession(s));
        }
      } catch {
        // Non-JSON message
      }
    };
    wsRef.current = ws;
  };

  // ── Effects ─────────────────────────────────────────────

  useEffect(() => {
    fetchSessions();
    fetchAgents();
    const interval = setInterval(() => {
      fetchAgents();
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchSessions, fetchAgents]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [currentSession?.messages?.length]);

  // ── Render ─────────────────────────────────────────────

  const messages = currentSession?.messages || [];

  return (
    <div className="h-screen flex bg-zinc-950 text-zinc-100">
      {/* ── Sidebar ── */}
      <div className="w-72 border-r border-zinc-800 flex flex-col">
        <div className="p-4 border-b border-zinc-800">
          <h1 className="text-lg font-bold flex items-center gap-2">
            <span className="text-2xl">⛓️</span> VoidTether
          </h1>
          <p className="text-xs text-zinc-500 mt-1">
            The cord that binds across the void
          </p>
        </div>

        {/* Sessions */}
        <div className="p-3 flex-1 overflow-y-auto">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-xs font-bold text-zinc-400 uppercase tracking-wider">
              Sessions
            </h2>
            <button
              onClick={createSession}
              className="px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-xs rounded"
            >
              + New
            </button>
          </div>
          {sessions.map((s) => (
            <button
              key={s.session_id}
              onClick={() => {
                setCurrentSession(s);
                connectWS(s.session_id);
              }}
              className={`w-full text-left p-2 rounded mb-1 text-sm ${
                currentSession?.session_id === s.session_id
                  ? "bg-zinc-800 text-zinc-100"
                  : "hover:bg-zinc-900 text-zinc-400"
              }`}
            >
              <span className="font-medium">{s.title}</span>
              <span className="text-xs text-zinc-600 ml-2">
                {s.messages.length} msgs
              </span>
            </button>
          ))}

          <h2 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mt-4 mb-2">
            Tethered Agents
          </h2>
          {agents.map((a) => (
            <AgentCard key={a.tether_id} agent={a} />
          ))}
          {agents.length === 0 && (
            <p className="text-xs text-zinc-600">
              No agents registered. Use the API to register agents.
            </p>
          )}
        </div>

        {/* Status */}
        <div className="p-3 border-t border-zinc-800 text-xs text-zinc-600">
          <div className="flex items-center gap-1">
            <span
              className={`w-2 h-2 rounded-full ${
                wsConnected ? "bg-emerald-400" : "bg-red-400"
              }`}
            />
            {wsConnected ? "Connected" : "Disconnected"}
          </div>
          <div className="mt-1">
            {agents.length} agents • {sessions.length} sessions
          </div>
        </div>
      </div>

      {/* ── Main chat area ── */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-zinc-800">
          <span className="font-bold">
            {currentSession?.title || "Select or create a session"}
          </span>
          {currentSession && (
            <span className="text-xs text-zinc-500 ml-3">
              {currentSession.participants.length} participants •{" "}
              {currentSession.turn_policy} • turn {currentSession.current_turn}
            </span>
          )}
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {messages.map((msg) => (
            <MessageBubble key={msg.message_id} msg={msg} />
          ))}
          {messages.length === 0 && (
            <div className="text-center text-zinc-600 py-20">
              <p className="text-4xl mb-4">⛓️</p>
              <p className="text-lg">VoidTether Mesh</p>
              <p className="text-sm mt-2">
                Create a session and interact with tethered agents
              </p>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="p-4 border-t border-zinc-800">
          <div className="flex gap-2">
            <input
              type="text"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && sendMessage()}
              placeholder="Send a message to the mesh..."
              disabled={!currentSession}
              className="flex-1 bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-zinc-500 disabled:opacity-50"
            />
            <button
              onClick={sendMessage}
              disabled={!currentSession || !inputMessage.trim()}
              className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 rounded text-sm font-medium"
            >
              Send
            </button>
          </div>
        </div>
      </div>

      {/* ── Event log sidebar ── */}
      <div className="w-72 border-l border-zinc-800 flex flex-col">
        <div className="p-3 border-b border-zinc-800">
          <h2 className="text-xs font-bold text-zinc-400 uppercase tracking-wider">
            Mesh Events
          </h2>
        </div>
        <div className="flex-1 overflow-y-auto p-3 space-y-1">
          {eventLog.map((e, i) => (
            <div key={i} className="text-xs text-zinc-500 font-mono">
              {e}
            </div>
          ))}
          {eventLog.length === 0 && (
            <p className="text-xs text-zinc-600">No events yet</p>
          )}
        </div>
      </div>
    </div>
  );
}