# Frontend Module Boundaries

This document defines the current frontend file boundaries for the stock system.
The goal is to keep page code small, predictable, and easy to move later if the
project adopts a bundler or framework.

## Core Utilities

- `static/js/ui_utils.js`
  - Shared UI helpers such as toast, escaping, navigation, and common DOM helpers.
  - Must not contain business-specific API calls.
- `static/js/core/api.js`
  - The only shared wrapper around `fetch`.
  - New code should use `StockApi.getJson`, `StockApi.postJson`,
    `StockApi.putJson`, or `StockApi.deleteJson` instead of direct `fetch`.
  - Background task responses should be passed through `StockApi.watchJob`.
- `static/js/core/formatters.js`
  - Shared display formatting for numbers, percentages, money, shares, and dates.
  - New modules should reuse `StockFormat` before adding local formatter helpers.

## Stock Detail

- `static/js/stock_detail.js`
  - Detail page shell only: route handling, top-level stock info, tab switching,
    portfolio position card, and calls that coordinate detail tabs.
  - Do not add a full tab implementation here.
- `static/js/detail/*.js`
  - One stock-detail tab or detail feature per file.
  - Examples: dividends, financing, shareholders, valuation, K-line, IRM, compare
    dashboard, and fundamental dashboard.
  - A new detail tab should get a new file under this directory.

## Financial Statements

- `static/js/financial_tables.js`
  - Financial tab shell and custom financial report view.
  - Shared financial-table coordination may live here, but source-specific logic
    should stay in the modules below.
- `static/js/financial/*.js`
  - Financial statement submodules.
  - Keep balance sheet, standard statements, revenue segments, and indicator
    preferences separated.
  - Shared period or metric rules should preferably live in backend services
    first, then be exposed through APIs.

## Home, Notes, Settings, Jobs

- `static/js/stock_list.js`
  - Home stock list, sorting, realtime cells, add/delete stock, and list order.
- `static/js/notes_chat.js`
  - Sticky notes and Munger chat.
- `static/js/local_settings.js`
  - Local user settings.
- `static/js/cloud_backup.js`
  - Cloud backup and restore flow.
- `static/js/background_jobs.js`
  - Floating background task panel and polling.

## Portfolio Page

- `templates/portfolio.html`
  - Portfolio page markup and modal structure only.
  - Do not add large inline scripts here; new behavior should live in
    `static/js/portfolio/`.
- `static/js/portfolio/state.js`
  - Portfolio page global state, startup wiring, default dates, and theme/chart
    refresh coordination.
  - `PortfolioState` is the single state container for portfolio data, fee
    config, chart instances, trade pagination, position sorting, NAV history,
    and privacy mode.
  - State writes should go through helpers such as `setPortfolioData`,
    `setFeeConfig`, `setTradesRows`, and `setNavHistoryRows` when one exists.
- `static/js/portfolio/api.js`
  - Portfolio API semantic wrapper.
  - Portfolio feature modules should call `PortfolioApi.*` instead of writing
    `StockApi.*` URLs directly.
- `static/js/portfolio/layout.js`
  - Portfolio layout helpers, modal open/close helpers, fee configuration,
    allocation pie chart, privacy toggle, and portfolio-specific formatting.
- `static/js/portfolio/positions.js`
  - Portfolio summary cards, position sorting, and position table rendering.
- `static/js/portfolio/render_records.js`
  - Trade and corporate action table rendering and pagination.
- `static/js/portfolio/trades_actions.js`
  - Buy/sell modal, corporate action modal, and trade/action loading or writes.
- `static/js/portfolio/render_ledger.js`
  - Cash-flow table rendering.
- `static/js/portfolio/ledger.js`
  - Cash-flow writes, trade/action voiding, account audit, ledger rebuild, and
    custom dividend settings.
- `static/js/portfolio/nav.js`
  - NAV snapshot creation, NAV chart rendering, NAV detail table pagination,
    filters, Excel export, resize handling, and the portfolio toast helper.
- `static/js/portfolio/earnings_calendar.js`
  - Earnings calendar modal based on NAV history, including daily calendar,
    monthly/yearly aggregation, and amount/rate display switching.

## Script Loading Order

Scripts are loaded in `templates/index.html` in this order:

1. Core utilities: `ui_utils.js`, `core/api.js`, `core/formatters.js`.
2. Stock detail shell and detail tabs.
3. Financial tab shell and financial submodules.
4. Home list, notes, backup, settings, and background jobs.

Scripts are loaded in `templates/portfolio.html` in this order:

1. Core utilities: `core/api.js`, `core/formatters.js`.
2. Portfolio API wrapper.
3. Portfolio state and startup wiring.
4. Portfolio layout helpers and portfolio-compatible formatter wrappers.
5. Positions.
6. Trade/action renderers.
7. Trades and corporate actions.
8. Ledger renderers.
9. Ledger/cash-flow maintenance.
10. NAV chart and NAV history.
11. Earnings calendar.
12. Shared cloud backup and background job scripts.

New modules must not depend on files loaded after them. If a helper is needed by
multiple modules, move it into `static/js/core/` or a clearly named shared module
loaded before its users.

## Rules For New Frontend Work

- Avoid direct `fetch` outside `static/js/core/api.js`.
- Avoid copy-pasted number, money, percentage, share, or date formatting outside
  `static/js/core/formatters.js`.
- Keep one feature or tab per file where possible.
- Do not add large inline scripts to `templates/index.html`; place behavior in a
  dedicated JavaScript file and load it from the template.
- Prefer backend APIs for business rules such as financial period selection,
  metric formulas, and incremental update decisions.
