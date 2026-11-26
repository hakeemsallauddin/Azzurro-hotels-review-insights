import React, { useEffect, useMemo, useState } from 'react';
import {
  Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, BarChart3,
  CalendarDays, Check, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, ClipboardCheck, Download,
  Hotel, MessageSquareText, RefreshCw, Search, Star, ThumbsDown, ThumbsUp, TrendingUp,
} from 'lucide-react';
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import Operations from './Operations.jsx';
import Automation from './Automation.jsx';

const API = `${(import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')}/api`;
const PROPERTIES = [
  ['all', 'All properties'],
  ['olympic-paddington', 'Olympic Hotel Paddington'],
  ['venus-potts-point-sydney', 'Potts Point'],
  ['venus-surry-hills', 'Central Sydney'],
  ['chateau-de-venus', 'Darling Harbour'],
];

async function get(path) {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) throw new Error(`API ${response.status}`);
  return response.json();
}

function sydneyIsoDate(value = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Australia/Sydney', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(value);
  const fields = Object.fromEntries(parts.map(({ type, value: part }) => [type, part]));
  return `${fields.year}-${fields.month}-${fields.day}`;
}

function sydneyOffsetDate(days = 0) {
  const [year, month, day] = sydneyIsoDate().split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day - days)).toISOString().slice(0, 10);
}

function downloadCsv(items) {
  const fields = [
    'review_id', 'property_name', 'review_date', 'reviewer_name', 'reviewer_country',
    'rating', 'traveller_type', 'room_type', 'title', 'positive_text', 'negative_text',
    'sentiment', 'topics', 'hotel_reply',
  ];
  const escape = (value) => `"${String(Array.isArray(value) ? value.join('; ') : (value ?? '')).replaceAll('"', '""')}"`;
  const csv = [fields.join(','), ...items.map((row) => fields.map((field) => escape(row[field])).join(','))].join('\r\n');
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob(['\ufeff', csv], { type: 'text/csv;charset=utf-8' }));
  link.download = 'azzurro-reviews-current-page.csv';
  link.click();
  URL.revokeObjectURL(link.href);
}

function Kpi({ label, value, icon, tone = 'blue', foot }) {
  return <article className="kpi"><div className="kpi-top"><span>{label}</span><div className={`kpi-icon ${tone}`}>{icon}</div></div><strong>{value}</strong><small>{foot}</small></article>;
}

function ReviewInsights({ data, filters, setFilters }) {
  const overview = data.overview ?? {};
  const page = data.reviews ?? { items: [], total_count: 0, total_pages: 1, page: 1, page_size: filters.pageSize };
  const topics = data.topics ?? [];
  const propertyCount = (data.properties ?? []).length;
  const rating = (value) => value == null ? '—' : Number(value).toFixed(1);
  const delta = (value) => value == null ? '—' : `${value > 0 ? '+' : ''}${Number(value).toFixed(2)}`;
  const changePage = (next) => setFilters((current) => ({ ...current, page: Math.max(1, Math.min(next, page.total_pages)) }));

  return <>
    <section className="filters">
      <label><span>PROPERTY</span><select value={filters.property} onChange={(event) => setFilters((current) => ({ ...current, property: event.target.value, page: 1 }))}>{PROPERTIES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <label><span>DATE RANGE</span><select value={filters.range} onChange={(event) => setFilters((current) => ({ ...current, range: event.target.value, page: 1 }))}><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option><option value="all">All time</option><option value="custom">Custom range</option></select></label>
      {filters.range === 'custom' && <><label><span>FROM</span><input type="date" value={filters.customStart} onChange={(event) => setFilters((current) => ({ ...current, customStart: event.target.value, page: 1 }))} /></label><label><span>TO</span><input type="date" value={filters.customEnd} onChange={(event) => setFilters((current) => ({ ...current, customEnd: event.target.value, page: 1 }))} /></label></>}
      <div className="filter-note"><CalendarDays size={15} /> Dates and property update the insights below</div>
    </section>

    <section className="kpis">
      <Kpi label="CURRENT WEEK · AVG RATING" value={rating(overview.current_week_avg)} icon={<Star />} foot={`Out of 10 · ${(overview.current_week_count || 0).toLocaleString()} reviews to date`} />
      <Kpi label="WEEK OVER WEEK" value={delta(overview.wow_delta)} icon={overview.wow_delta >= 0 ? <ArrowUpRight /> : <ArrowDownRight />} tone={overview.wow_delta < 0 ? 'red' : 'green'} foot={`Previous week ${rating(overview.previous_week_avg)} · ${(overview.previous_week_count || 0).toLocaleString()} reviews`} />
      <Kpi label="REVIEWS IN SELECTED PERIOD" value={(overview.total_reviews || 0).toLocaleString()} icon={<MessageSquareText />} tone="purple" foot="Use All time to browse the full stored dataset" />
      <Kpi label="NEGATIVE REVIEW RATE" value={`${overview.negative_rate || 0}%`} icon={<ThumbsDown />} tone="amber" foot={`${(overview.negative_count || 0).toLocaleString()} negative reviews`} />
    </section>

    <section className="takeaways-panel"><div className="takeaways-heading"><Activity size={14} /><span>OPERATIONAL KEY TAKEAWAYS</span><small>{filters.property === 'all' ? 'All properties' : PROPERTIES.find(([value]) => value === filters.property)?.[1]} · {filters.range === 'all' ? 'All time' : `${dateQueryStart(filters)} – ${dateQueryEnd(filters)}`}</small></div>{overview.takeaways?.length ? <div className="takeaway-grid">{overview.takeaways.map((item, index) => { const content = <><span className="takeaway-bullet" aria-hidden="true" /><span>{item.message}</span></>; return item.topic ? <button type="button" className={`takeaway-item ${item.kind}`} key={`${item.kind}-${index}`} onClick={() => setFilters((current) => ({ ...current, topic: item.topic, sentiment: item.sentiment, page: 1 }))} title="Open matching guest reviews">{content}</button> : <div className={`takeaway-item ${item.kind}`} key={`${item.kind}-${index}`}>{content}</div>; })}</div> : <div className="takeaways-empty">There are not enough dated reviews in this selection to calculate these takeaways.</div>}</section>

    <section className="property-section"><div className="section-head"><div><h2>Property performance</h2><p>Collected review averages and Booking.com’s separately reported listing score</p></div><span className="muted">{propertyCount} properties</span></div><div className="property-grid">{(data.properties ?? []).map((property) => <article className="property-card" key={property.property}>
      <div className="property-title"><div className="property-icon"><Hotel size={16} /></div><b>{property.name}</b></div>
      <div className="property-score-pair"><div><small>Selected-period review mean</small><strong>{rating(property.average_rating)}<em>/10</em></strong><span>{property.review_count.toLocaleString()} in selected period</span></div><div><small>Booking.com score</small><strong>{property.booking_overall_score == null ? '—' : Number(property.booking_overall_score).toFixed(1)}<em>{property.booking_overall_score == null ? '' : '/10'}</em></strong><span>{property.source_observed_at ? `Observed ${new Date(property.source_observed_at).toLocaleDateString()}` : 'Not captured yet'}</span></div></div>
      <div className="property-signals"><div><small>Top issue</small><b>{property.top_complaint ? `${property.top_complaint} · ${property.top_complaint_share}%` : 'No tagged complaints'}</b></div><div><small>Top praise</small><b>{property.top_praise ? `${property.top_praise} · ${property.top_praise_share}%` : 'No tagged praise'}</b></div></div>
      <div className="property-bottom"><span>WoW {delta(property.wow_delta)}</span><span>{property.booking_total_reviews == null ? `${property.stored_review_count.toLocaleString()} stored · listing total unknown` : `${property.stored_review_count.toLocaleString()} stored / ${property.booking_total_reviews.toLocaleString()} listed`}</span></div>
      <a className="listing-link" href={property.url} target="_blank" rel="noreferrer">View Booking.com listing</a>
    </article>)}</div></section>

    <section className="charts"><div className="panel"><div className="panel-head"><div><h2>Positive and negative review trends</h2><p>Weekly sentiment volume and average rating</p></div></div><div className="chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={data.trends ?? []} margin={{ left: -15, right: 10, top: 10, bottom: 0 }}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf0f5" /><XAxis dataKey="period" tick={{ fontSize: 11, fill: '#8791a3' }} tickFormatter={(value) => value?.slice(5)} /><YAxis yAxisId="left" tick={{ fontSize: 11, fill: '#8791a3' }} /><YAxis yAxisId="right" orientation="right" domain={[0, 10]} tick={{ fontSize: 11, fill: '#8791a3' }} /><Tooltip /><Legend /><Line yAxisId="left" type="monotone" dataKey="positive" name="Positive" stroke="#2d9b75" strokeWidth={2} dot={false} /><Line yAxisId="left" type="monotone" dataKey="negative" name="Negative" stroke="#df6d68" strokeWidth={2} dot={false} /><Line yAxisId="right" type="monotone" dataKey="average_rating" name="Average rating" stroke="#456be8" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></div></div>
      <div className="panel"><div className="panel-head"><div><h2>Operational topics</h2><p>Share of negative reviews mentioning each topic · select to filter</p></div></div><div className="chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={topics} layout="vertical" margin={{ left: 10, right: 15, top: 2, bottom: 0 }} onClick={(event) => { const selected = event?.activePayload?.[0]?.payload?.topic; if (selected) setFilters((current) => ({ ...current, topic: current.topic === selected ? '' : selected, page: 1 })); }}><CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#edf0f5" /><XAxis type="number" tick={{ fontSize: 10, fill: '#8791a3' }} /><YAxis type="category" dataKey="topic" width={118} tick={{ fontSize: 10, fill: '#69758a' }} /><Tooltip /><Bar dataKey="negative_mentions" name="Negative reviews" fill="#6d83eb" radius={[0, 4, 4, 0]} cursor="pointer" /></BarChart></ResponsiveContainer></div></div></section>

    <section className="reviews panel"><div className="review-head"><div><h2>Guest review feed <span className="count-badge">{page.total_count.toLocaleString()}</span></h2><p>Browse individual guest feedback; pagination covers every review in the selected period</p></div><button className="export" onClick={() => downloadCsv(page.items)} disabled={!page.items.length}><Download size={15} /> Export this page</button></div>
      <div className="review-controls"><label className="search"><Search size={16} /><input aria-label="Search reviews" placeholder="Search comments, guests, or properties…" value={filters.q} onChange={(event) => setFilters((current) => ({ ...current, q: event.target.value, page: 1 }))} /></label><select aria-label="Filter reviews by sentiment" value={filters.sentiment} onChange={(event) => setFilters((current) => ({ ...current, sentiment: event.target.value, page: 1 }))}><option value="">All sentiments</option><option value="positive">Positive</option><option value="neutral">Neutral</option><option value="negative">Negative</option></select><select aria-label="Sort reviews" value={filters.sort} onChange={(event) => setFilters((current) => ({ ...current, sort: event.target.value, page: 1 }))}><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="highest">Highest rated</option><option value="lowest">Lowest rated</option></select><select aria-label="Reviews per page" value={filters.pageSize} onChange={(event) => setFilters((current) => ({ ...current, pageSize: Number(event.target.value), page: 1 }))}><option value="25">25 per page</option><option value="50">50 per page</option><option value="100">100 per page</option></select>{filters.topic && <button className="topic-clear" onClick={() => setFilters((current) => ({ ...current, topic: '', page: 1 }))}>{filters.topic} ×</button>}</div>
      <div className="review-list">{page.items.map((review) => <article className="review" key={review.review_id}><div className={`score ${review.rating < 6 ? 'score-low' : review.rating < 8 ? 'score-mid' : ''}`}>{review.rating ?? '—'}<small>/10</small></div><div className="review-body"><div className="review-meta"><b>{review.property_name}</b><span>{review.review_date || 'Date unavailable'}</span><span>{review.reviewer_country || 'Country unknown'}</span></div><div className="reviewer">{review.reviewer_name || 'Guest'}{review.traveller_type && <span> · {review.traveller_type}</span>}{review.room_type && <span> · {review.room_type}</span>}<span className={`sentiment ${review.sentiment}`}>{review.sentiment}</span></div>{review.title && <h3>{review.title}</h3>}{(review.positive_text || review.negative_text) && <div className="review-text">{review.positive_text && <p><ThumbsUp size={14} />{review.positive_text}</p>}{review.negative_text && <p className="negative-text"><ThumbsDown size={14} />{review.negative_text}</p>}</div>}{review.topics?.length > 0 && <div className="tags">{review.topics.map((item) => <button key={item} onClick={() => setFilters((current) => ({ ...current, topic: item, page: 1 }))}>{item}</button>)}</div>}{review.hotel_reply && <div className="reply"><b>Property reply</b><p>{review.hotel_reply}</p></div>}</div></article>)}{!page.items.length && <div className="empty"><MessageSquareText size={30} /><b>No reviews match these filters</b><span>{overview.total_reviews ? 'Try a wider date range or clear the topic, sentiment, and search filters.' : 'The database has no review records yet.'}</span></div>}</div>
      <div className="pagination"><span>Showing {page.total_count ? ((page.page - 1) * page.page_size + 1).toLocaleString() : 0}–{Math.min(page.page * page.page_size, page.total_count).toLocaleString()} of {page.total_count.toLocaleString()} reviews</span><div><button disabled={page.page <= 1} aria-label="First review page" onClick={() => changePage(1)}><ChevronsLeft size={16} /></button><button disabled={page.page <= 1} aria-label="Previous review page" onClick={() => changePage(page.page - 1)}><ChevronLeft size={16} /></button><span>Page {page.page} of {Math.max(1, page.total_pages)}</span><button disabled={page.page >= page.total_pages} aria-label="Next review page" onClick={() => changePage(page.page + 1)}><ChevronRight size={16} /></button><button disabled={page.page >= page.total_pages} aria-label="Last review page" onClick={() => changePage(page.total_pages)}><ChevronsRight size={16} /></button></div></div>
    </section>
    <p className="query-note">Showing data for {filters.range === 'all' ? 'all dates' : `${dateQueryStart(filters)} to ${dateQueryEnd(filters)}`} · {PROPERTIES.find(([value]) => value === filters.property)?.[1] || 'All properties'}</p>
  </>;
}

function dateQueryStart(filters) {
  if (filters.range === 'custom') return filters.customStart || 'start date';
  return sydneyOffsetDate(({ 7: 6, 30: 29, 90: 89 }[filters.range] ?? 29));
}

function dateQueryEnd(filters) {
  return filters.range === 'custom' ? (filters.customEnd || sydneyIsoDate()) : sydneyIsoDate();
}

export default function App() {
  const [tab, setTab] = useState('insights');
  const [filters, setFilters] = useState({ property: 'all', range: '30', customStart: '', customEnd: '', q: '', topic: '', sentiment: '', sort: 'newest', page: 1, pageSize: 100 });
  const [data, setData] = useState({});
  const [operations, setOperations] = useState(null);
  const [automation, setAutomation] = useState(null);
  const [error, setError] = useState('');
  const [featureError, setFeatureError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [sync, setSync] = useState(null);
  const [loading, setLoading] = useState(false);
  const [impactWindow, setImpactWindow] = useState(30);

  const dateQuery = useMemo(() => {
    if (filters.range === 'all') return {};
    if (filters.range === 'custom') return { ...(filters.customStart ? { start_date: filters.customStart } : {}), ...(filters.customEnd ? { end_date: filters.customEnd } : {}) };
    const days = ({ 7: 6, 30: 29, 90: 89 }[filters.range] ?? 29);
    return { start_date: sydneyOffsetDate(days), end_date: sydneyIsoDate() };
  }, [filters.range, filters.customStart, filters.customEnd]);
  const query = useMemo(() => new URLSearchParams({ ...dateQuery, property: filters.property }).toString(), [dateQuery, filters.property]);
  const reviewQuery = useMemo(() => new URLSearchParams({ ...dateQuery, property: filters.property, page: String(filters.page), page_size: String(filters.pageSize), sort: filters.sort, ...(filters.q ? { q: filters.q } : {}), ...(filters.topic ? { topic: filters.topic } : {}), ...(filters.sentiment ? { sentiment: filters.sentiment } : {}) }).toString(), [dateQuery, filters.property, filters.page, filters.pageSize, filters.sort, filters.q, filters.topic, filters.sentiment]);

  async function load() {
    setLoading(true);
    try {
      setError('');
      const [overview, properties, trends, topics, reviews, status] = await Promise.all([
        get(`/overview?${query}`), get(`/properties?${query}`), get(`/trends?${query}`), get(`/topics?${query}`),
        get(`/reviews?${reviewQuery}`), get('/scrape/status'),
      ]);
      setData({ overview, properties, trends, topics, reviews });
      setSync(status);
      const [opsResult, autoResult] = await Promise.allSettled([get(`/operations?property=${filters.property}&days=30`), get(`/automation?impact_window=${impactWindow}`)]);
      setOperations(opsResult.status === 'fulfilled' ? opsResult.value : null);
      setAutomation(autoResult.status === 'fulfilled' ? autoResult.value : null);
      setFeatureError(opsResult.status === 'rejected' || autoResult.status === 'rejected' ? 'Restart the backend API to load the new Operations & Actions and Automation & Impact data.' : '');
    } catch (exception) {
      setError(`${exception.message} — check that the API is running at 127.0.0.1:8000.`);
    } finally { setLoading(false); }
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, [query, reviewQuery, filters.property, impactWindow]);

  async function refresh(mode = 'incremental') {
    setRefreshing(true); setError('');
    try {
      const response = await fetch(`${API}/scrape/trigger?mode=${mode}`, { method: 'POST' });
      if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || body.error || `API ${response.status}`); }
      setSync((current) => ({ ...current, status: 'running' }));
      for (let attempt = 0; attempt < 180; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const status = await get('/scrape/status'); setSync(status);
        if (!status.is_running && status.status !== 'running') break;
      }
      await load();
    } catch (exception) { setError(`Could not refresh reviews: ${exception.message}`); }
    finally { setRefreshing(false); }
  }

  const navItems = [
    ['insights', <BarChart3 size={17} />, 'Review Insights'],
    ['operations', <ClipboardCheck size={17} />, 'Operations & Actions'],
    ['automation', <TrendingUp size={17} />, 'Automation & Impact'],
  ];
  const count = automation?.review_count ?? data.overview?.total_reviews ?? 0;

  return <div className="shell">
    <aside className="sidebar"><div className="brand"><div className="brand-icon"><Hotel size={21} /></div><div><b>AZZURRO</b><small>HOTEL GROUP</small></div></div><div className="side-label">WORKSPACE</div><nav className="side-nav" aria-label="Dashboard sections">{navItems.map(([id, icon, label]) => <button key={id} className={`nav ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)} aria-current={tab === id ? 'page' : undefined}>{icon}<span>{label}</span>{id === 'operations' && operations?.actions?.filter((item) => item.status !== 'completed').length > 0 && <b className="nav-count">{operations.actions.filter((item) => item.status !== 'completed').length}</b>}</button>)}</nav><div className="side-foot"><div className="live-dot" />Connected to local review database</div></aside>
    <main className="main">
      <header className="top"><div><div className="eyebrow">OPERATIONS OVERVIEW</div><h1>{tab === 'insights' ? 'Guest review intelligence' : tab === 'operations' ? 'Operations & actions' : 'Automation & impact'}</h1><p>{tab === 'insights' ? 'Understand guest experience across your properties.' : tab === 'operations' ? 'Turn recurring guest feedback into owned, trackable work.' : 'Monitor collection health and review performance over time.'}</p></div><div className="top-meta"><span className="status-pill"><i /> {error ? 'Needs attention' : 'Database connected'}</span><span className="sync-label">{sync?.finished_at ? `Last sync ${new Date(sync.finished_at).toLocaleString()}` : 'No completed sync yet'}</span><button className="primary" onClick={() => refresh('incremental')} disabled={refreshing}><RefreshCw size={15} className={refreshing ? 'spin' : ''} />{refreshing ? sync?.status === 'waiting_for_verification' ? 'Waiting for verification…' : 'Collecting…' : 'Refresh reviews'}</button></div></header>
      <div className="view-meta"><span className="dataset-count"><MessageSquareText size={15} />{count.toLocaleString()} stored reviews</span><span className="scope-label">{filters.property === 'all' ? 'All 4 properties' : PROPERTIES.find(([value]) => value === filters.property)?.[1]}</span></div>
      {error && <div className="error" role="alert"><AlertTriangle size={16} />{error}</div>}
      {featureError && <div className="scrape-warning" role="status"><AlertTriangle size={16} />{featureError}</div>}
      {sync?.status === 'waiting_for_verification' && <div className="scrape-warning" role="status"><AlertTriangle size={16} /><span>Complete Booking.com’s verification in the visible browser window. The scraper will resume automatically; you do not need to press Enter.</span></div>}
      {tab === 'insights' && <ReviewInsights data={data} filters={filters} setFilters={setFilters} />}
      {tab === 'operations' && <Operations data={operations} property={filters.property} onChanged={load} onInspectTopic={(topic, sentiment = 'negative') => { setTab('insights'); setFilters((current) => ({ ...current, range: '30', sentiment, topic, page: 1 })); }} />}
      {tab === 'automation' && <Automation data={automation} sync={sync} loading={loading} impactWindow={impactWindow} onImpactWindowChange={setImpactWindow} onRefresh={load} onSync={() => refresh('incremental')} onBackfill={() => refresh('full')} />}
      {loading && <div className="loading-strip" role="status">Refreshing dashboard data…</div>}
      <footer>Azzurro Hotels · Guest review operations · Review analysis is descriptive and based on available stored records.</footer>
    </main>
  </div>;
}
