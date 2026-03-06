<div align="center">

<img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
<img src="https://img.shields.io/badge/FastAPI-0.111-009688?style=for-the-badge&logo=fastapi&logoColor=white"/>
<img src="https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=black"/>
<img src="https://img.shields.io/badge/MongoDB-7.0-47A248?style=for-the-badge&logo=mongodb&logoColor=white"/>
<img src="https://img.shields.io/badge/Status-MVP-F4A261?style=for-the-badge"/>

# 🧠 Enterprise Knowledge Management (EKM)

**One search. Every knowledge source. Instant answers.**

EKM unifies **SharePoint**, **Confluence**, **Jira**, and **GitHub Enterprise** into a single MongoDB-backed search engine — with BM25 relevance ranking, SME identification, entity extraction, and code intelligence.

[Features](#-features) · [Architecture](#-architecture) · [Quick Start](#-quick-start) · [Configuration](#-configuration) · [API Reference](#-api-reference) · [Roadmap](#-roadmap)

</div>

---

## 💡 Why EKM?

> Employees at large organisations spend **up to 20% of their working week** searching for information — one full day per person, per week, wasted.

Knowledge lives in silos. Engineers work in Jira. Processes live in Confluence. Policies sit in SharePoint. Code history is buried in GitHub. When someone needs an answer, they search four tools, skim dozens of results, and still might not find it.

**EKM fixes this** — one query, every source, instant results.

---

## ✨ Features

### Core Search
- 🔍 **BM25 full-text search** — relevance-ranked results across all sources with field weighting (title 10×, tags 5×, content 1×)
- 🏷️ **Source filtering** — narrow to SharePoint / Confluence / Jira / GitHub instantly
- 🔄 **Incremental sync** — only changed documents upserted on each run (APScheduler, configurable interval)
- 📊 **Live dashboard** — per-source doc counts, sync status, activity log

### Intelligence Layer
- 🏆 **SME Ranking** — identifies top 5 subject-matter experts for any search query based on authorship, assignment, and contribution signals with recency weighting
- 💡 **Best Answer extraction** — surfaces the most relevant passage from top results
- 🏷️ **Entity extraction** — auto-detects Jira tickets, change numbers, versions, environments, dates from all content
- 🔗 **Cross-linking** — Jira issues linked to GitHub commits, Confluence pages linked to Jira tickets

### Code Intelligence (GitHub)
- 📦 **Commit indexing** — full diff, file list, author, stats
- 📄 **Source file crawl** — READMEs, code files across all major languages
- 🔀 **PR indexing** — merged pull requests with description
- 🔍 **Explain this code** — 4-signal analysis per commit/file:
  - **Signal 1 — Jira cross-link**: commit message `PROJ-123` → fetches Jira ticket → business reason, status, priority
  - **Signal 2 — PR body**: finds PR containing the commit SHA → technical rationale
  - **Signal 3 — Static diff analysis**: new/modified/deleted functions, new API endpoints, DB changes, new imports
  - **Signal 4 — Architecture docs**: matches module names against Confluence/SharePoint → architectural context

### Data Sources
| Source | Auth | Content |
|--------|------|---------|
| **Jira** (on-premise) | PAT token | Issues, comments, ADF bodies, metadata |
| **Confluence** (on-premise) | PAT token | Pages, spaces, HTML → plain text |
| **SharePoint Online** | Configurable | SitePages, document libraries (.docx .pptx .xlsx .pdf) |
| **GitHub Enterprise** | PAT token | Commits, code files, pull requests |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         EKM Architecture                                    │
├────────────────┬──────────────────┬───────────────────┬────────────────────┤
│  DATA SOURCES  │   CONNECTORS     │   CORE ENGINE     │   FRONTEND         │
├────────────────┼──────────────────┼───────────────────┼────────────────────┤
│                │                  │                   │                    │
│  Jira ─────────┤─ jira.py         │                   │  Dashboard         │
│  Confluence ───┤─ confluence.py   │  sync_service.py  │  • Source cards    │
│  SharePoint ───┤─ sharepoint.py   │  ─────────────    │  • Sync controls   │
│  GitHub GHE ───┤─ github.py       │  MongoDB          │  • Activity log    │
│                │                  │  • Full-text idx  │                    │
│                │  INTELLIGENCE    │  • Unique upsert  │  Search            │
│                │  ─────────────── │  • Entities       │  • BM25 results    │
│                │  bm25.py         │                   │  • Source filter   │
│                │  sme_ranker.py   │  FastAPI           │  • SME panel       │
│                │  extractor.py    │  /api/search      │  • Best answer     │
│                │  code_explainer  │  /api/sync        │  • GitHub cards    │
│                │  file_extractor  │  /api/explain/:id │  • Explain panel   │
│                │                  │  /api/sources     │                    │
│                │                  │  /api/documents   │  Documents         │
│                │                  │                   │  • Browse/filter   │
└────────────────┴──────────────────┴───────────────────┴────────────────────┘
```

### Data Flow

1. **Connector** authenticates to source system and fetches documents
2. Documents normalised to common `Document` schema with `entities` extraction
3. **Sync service** upserts into MongoDB using `(source_type, external_id)` as unique key
4. MongoDB **text indexes** on `title` (10×), `tags` (5×), `content` (1×) power BM25 search
5. **SME ranker** scores contributors across all matched docs, returns top 5 experts
6. **Code explainer** assembles 4-signal explanations for GitHub commits/files
7. **React frontend** renders results, SME panel, best answer, and inline explain cards

---

## 📁 Project Structure

```
ekm-mvp/
│
├── start-backend.bat / .sh       ← one-command backend startup
├── start-frontend.bat / .sh      ← one-command frontend startup
├── setup-sharepoint.bat          ← SharePoint dependency installer
├── sharepoint_sites.txt          ← SharePoint site URLs (one per line)
├── .env.example                  ← copy to backend/.env
│
├── backend/
│   ├── main.py                   ← FastAPI app, lifespan, CORS, scheduler
│   ├── config.py                 ← Pydantic settings (all sources configured here)
│   ├── database.py               ← Async MongoDB, index creation
│   ├── models.py                 ← Document, SyncLog, Entities, SourceType schemas
│   │
│   ├── connectors/
│   │   ├── jira.py               ← JQL fetch, ADF→text, comments, metadata
│   │   ├── confluence.py         ← Atlassian API, HTML→text, space crawl
│   │   ├── sharepoint.py         ← REST API, SitePages + doc libraries
│   │   └── github.py             ← GHE commits, files, PRs (PAT auth)
│   │
│   ├── routes/
│   │   ├── search.py             ← BM25 search, SME ranking, best answer
│   │   ├── api.py                ← Sync, sources/stats, document CRUD
│   │   └── explain.py            ← GET /api/explain/:id — code intelligence
│   │
│   └── utils/
│       ├── sync_service.py       ← Orchestrates connectors, upserts to DB
│       ├── bm25.py               ← BM25 relevance scoring
│       ├── sme_ranker.py         ← SME scoring with recency weighting
│       ├── extractor.py          ← Entity extraction (tickets, CHG, versions, envs)
│       ├── file_extractor.py     ← docx/pptx/xlsx/pdf/txt text extraction
│       └── code_explainer.py     ← 4-signal GitHub commit/file analysis
│
└── frontend/src/
    ├── pages/
    │   ├── Dashboard.jsx         ← Stats, source cards, sync, activity log
    │   ├── Search.jsx            ← Search, filters, SME panel, GitHub cards, explain
    │   └── Documents.jsx         ← Paginated document browser
    └── components/UI.jsx         ← Shared UI components
```

---

## ⚡ Quick Start

### Prerequisites

| Tool | Version |
|------|---------|
| Conda (Miniconda/Anaconda) | Any |
| Node.js | 18+ |
| MongoDB | Running instance |

### 1 — Configure

```bash
cp .env.example backend/.env
# Edit backend/.env with your credentials
```

### 2 — Start backend

```bash
# Windows
start-backend.bat

# Mac/Linux
chmod +x start-backend.sh && ./start-backend.sh
```

Backend: **http://localhost:8000** · Swagger: **http://localhost:8000/docs**

### 3 — Start frontend (new terminal)

```bash
start-frontend.bat        # Windows
./start-frontend.sh       # Mac/Linux
```

Frontend: **http://localhost:3000**

### 4 — Sync and search

Click **Sync All** on the Dashboard, then go to **Search**.

---

## ⚙️ Configuration

All configuration lives in `backend/.env`. Copy from `.env.example`.

### MongoDB
```env
MONGO_URI=mongodb://user:pass@host:port/db?authMechanism=DEFAULT
MONGO_DB=your_database
```

### Jira (on-premise)
```env
JIRA_URL=https://your-jira.company.com
JIRA_USERNAME=your.name@company.com
JIRA_API_TOKEN=your-pat-token
JIRA_PROJECTS=PROJ1,PROJ2          # leave blank for all projects
```

### Confluence (on-premise)
```env
CONFLUENCE_URL=https://your-confluence.company.com/confluence
CONFLUENCE_USERNAME=your.name@company.com
CONFLUENCE_API_TOKEN=your-pat-token
CONFLUENCE_SPACES=ENG,OPS          # leave blank for all spaces
```

### GitHub Enterprise
```env
GITHUB_HOST=github.yourcompany.com          # GHE hostname (no https://)
GITHUB_TOKEN=your-ghe-pat-token            # PAT with repo (read) scope
GITHUB_REPOS=org/repo1,org/repo2           # specific repos
# GITHUB_ORG=your-org                      # OR crawl all repos in an org
GITHUB_MAX_COMMITS=200
```

### SharePoint
```env
SHAREPOINT_SITE_URLS=https://company.sharepoint.com/sites/site1
# Edit sharepoint_sites.txt for 10+ sites (one URL per line)
```

> For SharePoint auth, see `setup-sharepoint.bat` and `.env.example` for options.

### App
```env
SYNC_INTERVAL_MINUTES=60
MAX_RESULTS_PER_PAGE=20
```

---

## 📡 API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/search?q={query}` | BM25 search across all sources |
| `GET` | `/api/search?q={query}&source_type=jira` | Search filtered to one source |
| `GET` | `/api/search?q={query}&page=2` | Paginated results |
| `GET` | `/api/sources` | Dashboard stats — doc counts, sync status |
| `POST` | `/api/sync` | Trigger sync — all sources |
| `POST` | `/api/sync` | Trigger sync — one source `{"source_type": "github"}` |
| `GET` | `/api/sync/logs` | Recent sync history |
| `GET` | `/api/documents` | Browse all documents (paginated) |
| `GET` | `/api/documents?source_type=github` | Browse filtered by source |
| `GET` | `/api/documents/{id}` | Full document with entities |
| `GET` | `/api/explain/{id}` | 4-signal code explanation for GitHub docs |

---

## 🗺️ Roadmap

### Phase 2 — Search Quality
- [ ] Vector / semantic search (MongoDB Atlas Vector Search)
- [ ] Query autocomplete from indexed titles
- [ ] Highlighted matching snippets

### Phase 3 — Access & Security
- [ ] SSO via Azure AD / Okta
- [ ] Per-user permission filtering (respect source ACLs)
- [ ] Audit logging

### Phase 4 — More Sources
- [ ] ServiceNow (connector stub already at `connectors/servicenow.py`)
- [ ] Slack public channels
- [ ] Google Drive / Workspace

### Phase 5 — Intelligence
- [ ] RAG-based Q&A (answers, not just links)
- [ ] Knowledge graph — relationships between docs, people, topics
- [ ] Duplicate detection across sources

---

<div align="center">
Built as an enterprise MVP · Python + FastAPI + React + MongoDB
</div>
