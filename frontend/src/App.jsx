
import { useEffect, useRef, useState } from "react";
import FlightCard from "./FlightCard";
import TripPanel from "./TripPanel";
import {
  ArrowUpIcon,
  ChatIcon,
  PlaneIcon,
  ResetIcon,
  SparklesIcon,
  TakeoffIcon,
} from "./icons";
import { postJson } from "./api";
import "./App.css";

const WELCOME_MESSAGE = {
  role: "assistant",
  text: "Hi! Where would you like to fly today?",
};

const SUGGESTIONS = [
  "Cheapest flight from KUL to Bangkok tomorrow",
  "Direct AirAsia flights from KL to Penang on Friday",
  "Flights from KL to Tokyo next week",
  "Plan me a 6d5n itinerary in Mumbai",
];

// Quick replies handled here instead of being sent to the backend.
const PANEL_ACTIONS = {
  "Show itinerary": "itinerary",
  "Show flights": "flights",
};

// Weather replies contain markdown (**bold**, # headings); show them as plain text.
function cleanText(text) {
  return text
    .replace(/\*\*/g, "")
    .replace(/^#+\s*/gm, "")
    .replace(/^---$/gm, "")
    .trim();
}

function toAssistantMessage(data) {
  const hasFlights = data.flights?.length > 0;

  return {
    role: "assistant",
    text:
      data.reply ||
      (hasFlights ? "" : "I couldn't generate a response. Please try again."),
    flights: hasFlights ? data.flights : null,
    flightsLabel: data.flights_label,
    quickReplies: data.quick_replies || null,
  };
}

const CONNECTION_ERROR = {
  role: "assistant",
  text: "Sorry, I couldn't connect to the server. Please make sure the backend is running and try again.",
};

function App() {
  const [messages, setMessages] = useState([WELCOME_MESSAGE]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [trip, setTrip] = useState(null);
  const [activeTab, setActiveTab] = useState("itinerary");
  // Narrow screens show either the chat or the trip panel.
  const [showTrip, setShowTrip] = useState(false);
  const bottomRef = useRef(null);

  // Keep the newest message in view.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  // Build the itinerary; the panel shows progress meanwhile.
  async function runGenerate() {
    setTrip((previous) => ({ ...previous, stage: "generating" }));
    setActiveTab("itinerary");
    setShowTrip(true);

    try {
      const data = await postJson("/trip/generate");

      setMessages((previous) => [...previous, toAssistantMessage(data)]);
      setTrip((previous) => data.trip || { ...previous, stage: "collecting" });
    } catch (error) {
      console.error("Trip error:", error);
      setMessages((previous) => [...previous, CONNECTION_ERROR]);
      setTrip((previous) => ({ ...previous, stage: "collecting" }));
    }
  }

  async function sendMessage(text) {
    const question = text.trim();

    if (!question || isLoading) return;

    // Add the user's message to the chat.
    setMessages((previous) => [...previous, { role: "user", text: question }]);
    setInput("");
    setIsLoading(true);

    try {
      const data = await postJson("/chat", { message: question });

      setMessages((previous) => [...previous, toAssistantMessage(data)]);

      if (data.trip) {
        setTrip(data.trip);

        // The checklist is complete (or the user said "generate").
        if (data.trip.stage === "ready") {
          await runGenerate();
        }
      }
    } catch (error) {
      console.error("Chat error:", error);
      setMessages((previous) => [...previous, CONNECTION_ERROR]);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleGenerate() {
    if (isLoading) return;

    setMessages((previous) => [
      ...previous,
      { role: "user", text: "Generate my trip" },
    ]);
    setIsLoading(true);

    try {
      await runGenerate();
    } finally {
      setIsLoading(false);
    }
  }

  function handleQuickReply(reply) {
    if (PANEL_ACTIONS[reply]) {
      setActiveTab(PANEL_ACTIONS[reply]);
      setShowTrip(true);
    } else if (reply === "Generate my trip") {
      handleGenerate();
    } else {
      sendMessage(reply);
    }
  }

  function handleSubmit(event) {
    event.preventDefault();
    sendMessage(input);
  }

  function handleNewChat() {
    if (isLoading) return;

    // Clear the backend's memory of the conversation too.
    postJson("/reset").catch((error) => console.error("Reset error:", error));

    setMessages([WELCOME_MESSAGE]);
    setInput("");
    setTrip(null);
    setShowTrip(false);
  }

  const lastMessage = messages[messages.length - 1];
  const quickReplies =
    !isLoading && lastMessage.role === "assistant" ? lastMessage.quickReplies : null;

  return (
    <div className="page">
      <div
        className={`chat-card ${trip ? "has-trip" : ""} ${
          showTrip ? "show-trip" : ""
        }`}
      >
        <header className="chat-header">
          <div className="header-icon">
            <PlaneIcon size={22} />
          </div>

          <div className="header-text">
            <h1>FlightMate AI</h1>
            <p>Your personal flight-search assistant</p>
          </div>

          {trip && (
            <button
              type="button"
              className="trip-toggle"
              onClick={() => setShowTrip((value) => !value)}
            >
              <SparklesIcon size={14} />
              {showTrip ? "Chat" : "Trip"}
            </button>
          )}

          <button
            type="button"
            className="reset-button"
            onClick={handleNewChat}
            disabled={isLoading}
            aria-label="New chat"
            title="New chat"
          >
            <ResetIcon size={16} />
          </button>

          <span className="status-pill">{isLoading ? "Typing" : "Online"}</span>
        </header>

        <div className="workspace">
          <div className="chat-column">
            <main className="messages" aria-live="polite">
              {messages.length === 1 && !isLoading && (
                <section className="hero">
                  <div className="hero-icon">
                    <TakeoffIcon size={28} />
                  </div>
                  <h2>Where to next?</h2>
                  <p>
                    Compare flights, check the weather when you land, or plan a
                    whole trip.
                  </p>
                </section>
              )}

              {messages.map((message, index) => (
                <div key={index} className={`message ${message.role}`}>
                  {message.role === "assistant" && (
                    <div className="avatar">
                      <PlaneIcon size={16} />
                    </div>
                  )}

                  <div className="message-body">
                    {message.text && (
                      <div className="bubble">{cleanText(message.text)}</div>
                    )}

                    {message.flights && (
                      <FlightCard
                        flights={message.flights}
                        label={message.flightsLabel}
                      />
                    )}
                  </div>
                </div>
              ))}

              {isLoading && (
                <div className="message assistant">
                  <div className="avatar">
                    <PlaneIcon size={16} />
                  </div>
                  <div className="message-body">
                    {trip?.stage === "generating" ? (
                      <div className="bubble">Building your trip…</div>
                    ) : (
                      <div className="bubble typing" aria-label="Thinking">
                        <span />
                        <span />
                        <span />
                      </div>
                    )}
                  </div>
                </div>
              )}

              {messages.length === 1 && !isLoading && (
                <div className="suggestions">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      type="button"
                      key={suggestion}
                      onClick={() => sendMessage(suggestion)}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              )}

              <div ref={bottomRef} />
            </main>

            <footer className="composer">
              {quickReplies && (
                <div className="quick-replies">
                  {quickReplies.map((reply) => (
                    <button
                      type="button"
                      key={reply}
                      className={reply === "Generate my trip" ? "primary" : ""}
                      onClick={() => handleQuickReply(reply)}
                    >
                      {reply === "Generate my trip" && <SparklesIcon size={14} />}
                      {reply}
                    </button>
                  ))}
                </div>
              )}

              <form className="input-box" onSubmit={handleSubmit}>
                <span className="input-icon">
                  <ChatIcon size={18} />
                </span>

                <input
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  placeholder="Ask about flights, weather or plan a trip..."
                  aria-label="Ask about flights"
                  disabled={isLoading}
                />

                <button
                  type="submit"
                  disabled={!input.trim() || isLoading}
                  aria-label="Send message"
                >
                  <ArrowUpIcon size={16} />
                </button>
              </form>

              <p className="disclaimer">
                Live flights from Kiwi.com · Weather from Open-Meteo · Itineraries by Gemini
              </p>
            </footer>
          </div>

          {trip && (
            <TripPanel
              trip={trip}
              activeTab={activeTab}
              onTabChange={setActiveTab}
              onGenerate={handleGenerate}
              onClose={() => setShowTrip(false)}
              isBusy={isLoading}
            />
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
