import { useEffect, useState } from "react";

const CHAT_API_URL = import.meta.env.VITE_CHAT_API_URL;

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [responseId, setResponseId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [agents, setAgents] = useState([]);
  const [selectedAgent, setSelectedAgent] = useState(null);

  useEffect(() => {
    fetch(`${CHAT_API_URL}/agents`)
      .then((res) => res.json())
      .then((data) => {
        setAgents(data.agents);
        setSelectedAgent(data.default);
      })
      .catch(() => setError("Could not load agent list."));
  }, []);

  function handleAgentChange(e) {
    setSelectedAgent(e.target.value);
    setMessages([]);
    setResponseId(null);
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || loading) return;

    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${CHAT_API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, response_id: responseId, agent_name: selectedAgent }),
      });

      if (!res.ok) {
        throw new Error(`Request failed: ${res.status}`);
      }

      const data = await res.json();
      setResponseId(data.response_id);
      setMessages((prev) => [...prev, { role: "assistant", text: data.reply }]);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <div className="chat-container">
      <h1>Chat</h1>

      <select
        className="agent-select"
        value={selectedAgent ?? ""}
        onChange={handleAgentChange}
        disabled={loading || agents.length === 0}
      >
        {agents.map((agent) => (
          <option key={agent.name} value={agent.name}>
            {agent.label}
          </option>
        ))}
      </select>

      <div className="messages">
        {messages.map((m, i) => (
          <div key={i} className={`message ${m.role}`}>
            <span className="label">{m.role === "user" ? "You" : "Agent"}</span>
            <p>{m.text}</p>
          </div>
        ))}
        {loading && <div className="message assistant">
          <span className="label">Agent</span>
          <p>Thinking…</p>
        </div>}
      </div>

      {error && <div className="error">Error: {error}</div>}

      <div className="input-row">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Message the agent…"
          rows={2}
        />
        <button onClick={sendMessage} disabled={loading}>
          Send
        </button>
      </div>
    </div>
  );
}
