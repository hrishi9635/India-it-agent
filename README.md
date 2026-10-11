# Indian IT Results Agent & Dashboard

A free, open-source AI agent that follows the top 10 Indian IT companies. After each quarterly
results season it collects the numbers, reads the news, extracts the key insights with a free AI
model, and updates a detailed dashboard.

**Cost: ₹0.** Uses yfinance (Yahoo Finance data), Google News and Bing News feeds, a free AI model
(Groq's free tier, or Ollama on your own laptop), GitHub Actions and Streamlit Community Cloud.

## On your laptop (double-click, in order)
1. `1 - Set up` installs the add-ons (once)
2. `2 - Save my AI key` stores your free Groq key on your computer, outside this folder (once)
3. `3 - Run the agent` collects data and writes insights (5-15 minutes)
4. `4 - Open the dashboard` opens it in your browser

Windows: use the `(Windows).bat` files. Mac: right-click the `(Mac).command` files and choose Open.

## Folder map
| File | What it is |
|---|---|
| `companies.csv` | The 10 companies. Edit in Excel to add or swap companies. |
| `settings.txt` | Which AI service and model to use. No secrets here. |
| `run_agent.py` + `agent/` | The agent. |
| `app.py` | The dashboard. |
| `data/` | Everything the agent saves; the dashboard reads it. |
| `.github/workflows/agent.yml` | Runs the agent every day on GitHub, for free. |

Follow the step-by-step guide for putting it online.

Not investment advice. AI-extracted figures come from news coverage; check important numbers
against company fact sheets.
