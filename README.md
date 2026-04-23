# ✈️ Tripy AI — Multi-Agent Travel Planner

🚀 An AI-powered **multi-agent travel planning system** that generates flights, hotels, and personalized itineraries from natural language queries.

---

## 🌍 Overview

Tripy AI is a full-stack intelligent travel assistant that allows users to simply type:

> *“Plan a 5-day trip from Mumbai to Singapore under $1000”*

…and get:

* ✈️ Flight options
* 🏨 Hotel recommendations
* 🎯 Activities & itinerary
* 💰 Cost breakdown
* 🤖 AI-based suggestions

---

## 🧠 Architecture (Multi-Agent System)

This system uses a **multi-agent workflow**:

* ✈️ **Flight Agent** → Fetches & filters flight data
* 🏨 **Hotel Agent** → Finds accommodations
* 🎯 **Itinerary Agent** → Suggests activities & plans
* 💰 **Budget Agent** → Calculates total cost
* 🤖 **Orchestrator Agent** → Combines everything into final output

---

## 🛠️ Tech Stack

### 🔹 Backend

* **Python + FastAPI**
* Multi-agent orchestration
* Async workflows
* External APIs (Flights, Hotels)

### 🔹 Frontend

* **React (Vite)**
* Chat-based UI
* Axios for API calls

### 🔹 AI / LLM

* **Groq API (LLaMA / Mixtral)**
* Prompt engineering for structured outputs

---

## 📂 Project Structure

```
TRAVEL_BOOKING_MULTIAGENT/
│
├── backend_service/
│   ├── server.py              # FastAPI server
│   ├── travel_workflow.py    # Multi-agent orchestration
│   ├── telegram_notifier.py  # Alerts (optional)
│   ├── requirements.txt
│
├── web_app/
│   ├── src/
│   │   ├── App.jsx           # Main UI
│   │   ├── components/
│   ├── package.json
│
└── README.md
```

---

## ⚙️ Setup Instructions

### 1️⃣ Clone the repo

```bash
git clone https://github.com/TARIFUDDIN/tripy-ai.git
cd tripy-ai
```

---

### 2️⃣ Backend Setup

```bash
cd backend_service
pip install -r requirements.txt
```

Create `.env`:

```
GROQ_API_KEY=your_api_key
```

Run server:

```bash
uvicorn server:app --reload
```

---

### 3️⃣ Frontend Setup

```bash
cd web_app
npm install
npm run dev
```

---

## 💬 Example Queries

* “Flights from Mumbai to Dubai next weekend”
* “Plan a 7-day trip to Bali under $1500”
* “Cheapest flight to Singapore with hotels”
* “Luxury trip to Paris with activities”

---

## ✨ Features

* ✅ Natural language travel search
* ✅ Multi-agent architecture
* ✅ Budget-aware planning
* ✅ Flight + Hotel + Activity integration
* ✅ AI-generated recommendations
* ✅ Chat-based UI

---

## ⚠️ Current Limitations

* Uses **free APIs** → may return:

  * Estimated prices
  * Inconsistent timings
  * Limited hotel availability

* Not all routes are 100% real-time

---

## 🚧 Future Improvements

* 🔥 Real-time flight APIs (Amadeus production / Skyscanner)
* 🔥 Booking integration
* 🔥 User authentication (Firebase)
* 🔥 AI memory for personalized trips
* 🔥 Voice-based travel assistant

---

## 🔐 Security

* API keys stored securely using `.env`
* Sensitive data removed from Git history
* Follows best practices for secret management

---


## 🤝 Contributing

Pull requests are welcome! For major changes, open an issue first.

---

## 📬 Contact

👤 **Tarifuddin Ahmed**
🔗 GitHub: https://github.com/TARIFUDDIN

---

## ⭐ If you like this project

Give it a ⭐ on GitHub — it helps a lot!

---


## 🏁 Final Thought

Tripy AI is a step toward **autonomous AI travel agents** that can plan entire trips end-to-end.

---
