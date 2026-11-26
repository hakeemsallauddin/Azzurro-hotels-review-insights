import React, { useState } from 'react';
import { Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, CheckCircle2, CircleAlert, Clock3, Database, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react';

function when(value) {
  if (!value) return 'Not recorded';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function ago(hours) {
  if (hours == null) return 'No successful run';
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))}m ago`;
  if (hours < 48) return `${hours.toFixed(1)}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function Status({ status, error = '' }) {
  const normalized = status || 'unknown';
  const label = normalized === 'completed_with_errors' && /verification|anti-bot|captcha/i.test(error) ? 'Verification check' : normalized.replaceAll('_', ' ');
  return <span className={`run-status ${normalized}`}>{label}</span>;
}

function attemptMessage(error) {
  if (!error) return '';
  if (/verification|anti-bot|captcha/i.test(error)) return 'Booking.com verification appeared; no reviews were collected.';
  return error;
}

function errorCount(data) {
  return (data.recent_runs || []).filter((run) => run.status === 'failed' || run.status === 'completed_with_errors').length;
}

export default function Automation({ data, sync, loading, impactWindow, onImpactWindowChange, onRefresh, onSync, onBackfill }) {
  const [showRunHistory, setShowRunHistory] = useState(false);
  if (!data) return <div className="panel empty"><Activity size={28} /><b>{loading ? 'Loading automation status…' : 'Automation status unavailable'}</b></div>;
  const current = data.current_window ?? {};
  const previous = data.previous_window ?? {};
  const coverage = data.coverage ?? {};
  const collection = data.collection_health ?? {};
  const impact = data.impact_summary ?? {};
  const recentRuns = data.recent_runs ?? [];
  const properties = (data.properties ?? []).map((property) => {
    const scopedRuns = recentRuns.filter((run) => run.property_slug === property.property || run.property_slug == null);
    const latestSuccessful = property.last_successful_run || scopedRuns.filter((run) => run.status === 'completed' && !run.errors && run.pages > 0).sort((a, b) => (b.finished_at || '').localeCompare(a.finished_at || ''))[0] || null;
    const latestAttempt = property.last_run || scopedRuns.sort((a, b) => (b.started_at || '').localeCompare(a.started_at || ''))[0] || null;
    const matchingErrors = (latestAttempt?.errors || '').split(/\r?\n/).map((line) => line.trim()).filter((line) => line.startsWith(`${property.property}:`)).map((line) => line.slice(line.indexOf(':') + 1).trim());
    const attemptError = property.latest_attempt_error || (latestAttempt?.property_slug === property.property ? latestAttempt?.errors : matchingErrors.join('\n')) || property.last_error || '';
    const successAge = property.success_age_hours ?? (latestSuccessful?.finished_at ? Math.max(0, (Date.now() - new Date(latestSuccessful.finished_at).getTime()) / 3600000) : null);
    const snapshotDate = (property.source_observed_at || '').slice(0, 10);
    const todaySydney = new Intl.DateTimeFormat('en-CA', { timeZone: 'Australia/Sydney', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
    return { ...property, last_successful_run: latestSuccessful, success_age_hours: successAge, health_status: property.health_status || (successAge != null && successAge < 24 && snapshotDate >= todaySydney ? 'healthy' : latestSuccessful ? 'stale' : 'unknown'), latest_attempt_status: property.latest_attempt_status || property.latest_run_status || latestAttempt?.status || 'unknown', latest_attempt_at: property.latest_attempt_at || property.latest_run_at || latestAttempt?.finished_at || latestAttempt?.started_at || null, latest_attempt_error: attemptError };
  });
  const derivedHealthyCount = properties.filter((property) => property.health_status === 'healthy').length;
  const healthyCount = collection.healthy_count ?? derivedHealthyCount;
  const propertyCount = collection.property_count ?? properties.length;
  const collectionStatus = collection.status || (properties.length && derivedHealthyCount === properties.length ? 'healthy' : 'attention');
  const latestBlocked = properties.some((property) => property.latest_attempt_error);
  const activeRuns = recentRuns.filter((run) => run.status === 'running').length;
  const historyErrors = errorCount({ recent_runs: recentRuns.slice(0, 5) });
  const impactAvailable = Boolean(data.impact_summary);
  const overallStatus = collectionStatus;
  const ratingChange = data.rating_change;
  const negativeChange = data.negative_rate_change;

  return <div className="tab-content automation-content">
    <section className="page-intro"><div><span className="eyebrow">COLLECTION MONITOR</span><h2>Automation & impact</h2><p>Review collector freshness, listing coverage, backfill progress, and measured changes after completed actions.</p></div><div className="page-actions"><button className="secondary-button" onClick={onRefresh}><RefreshCw size={15} />Reload status</button><button className="secondary-button" onClick={onSync} disabled={sync?.is_running}><RefreshCw size={15} />Run incremental sync</button><button className="primary" onClick={onBackfill} disabled={sync?.is_running}><Database size={15} />Start full backfill</button></div></section>

    <section className={`collection-monitor ${overallStatus}`}>
      <div className="monitor-heading"><div className="monitor-title">{overallStatus === 'healthy' ? <CheckCircle2 size={17} /> : <CircleAlert size={17} />}<b>Collection Monitor: {healthyCount} of {propertyCount} properties healthy</b></div><span>Freshness uses each property's last successful collection</span></div>
      <div className="monitor-property-list">{properties.map((property) => <span className={`monitor-property ${property.health_status}`} key={property.property}><i />{property.name}: {property.review_count.toLocaleString()}{property.booking_total_reviews == null ? ' stored' : `/${property.booking_total_reviews.toLocaleString()}`} · {ago(property.success_age_hours)}</span>)}</div>
      {latestBlocked && <div className="monitor-note"><AlertTriangle size={15} /><span><b>Booking.com showed a verification check during the latest attempt.</b> {derivedHealthyCount === properties.length ? 'The previous successful collection is still within the 24-hour freshness window. ' : ''}No new reviews were collected in that attempt; property-specific details are available in the run history.</span></div>}
    </section>

    <section className="ops-summary impact-summary"><article className="summary-card tone-blue"><span><Database size={14} /> REVIEWS STORED</span><strong>{(data.review_count || 0).toLocaleString()}</strong><small>Rows in the local review database</small></article><article className="summary-card"><span>RECENT 30-DAY REVIEWS</span><strong>{(current.count || 0).toLocaleString()}</strong><small>{current.start} to {current.end}</small></article><article className={`summary-card ${ratingChange == null ? '' : ratingChange >= 0 ? 'tone-green' : 'tone-red'}`}><span>AVERAGE RATING CHANGE</span><strong>{ratingChange == null ? '—' : `${ratingChange > 0 ? '+' : ''}${Number(ratingChange).toFixed(2)}`}</strong><small>{previous.average ?? '—'} prior · {current.average ?? '—'} recent</small></article><article className={`summary-card ${negativeChange == null ? '' : negativeChange <= 0 ? 'tone-green' : 'tone-red'}`}><span>NEGATIVE RATE CHANGE</span><strong>{negativeChange == null ? '—' : `${negativeChange > 0 ? '+' : ''}${Number(negativeChange).toFixed(1)}%`}</strong><small>{previous.negative_rate ?? 0}% prior · {current.negative_rate ?? 0}% recent</small></article></section>

    <section className="panel coverage-panel" id="collection-coverage"><div className="panel-head"><div><h2><Database size={17} />Collection Coverage, Backfill Status & Automation Health</h2><p>Stored unique review rows compared with dated Booking.com listing snapshots. Coverage is a data gap measure, separate from collector freshness.</p></div><span className="window-pill">{activeRuns} active · {historyErrors} of the latest 5 runs had issues</span></div><div className="coverage-summary"><b>{(coverage.stored_reviews ?? data.review_count ?? 0).toLocaleString()} stored</b><span>/</span><b>{coverage.listing_reviews == null ? 'Listing total not captured' : `${coverage.listing_reviews.toLocaleString()} listed`}</b><span>{coverage.coverage_pct == null ? 'Coverage unknown' : `${coverage.coverage_pct}% of observed listing totals`}</span><span>{coverage.remaining_gap == null ? 'Gap unknown' : `${coverage.remaining_gap.toLocaleString()} review gap`}</span>{coverage.observed_at && <small>Source snapshot: {when(coverage.observed_at)}</small>}</div><div className="coverage-grid">{properties.map((property) => {
      const expected = property.booking_total_reviews;
      const status = property.backfill_status || 'source_total_unknown';
      const sourceDate = property.source_observed_at ? new Date(property.source_observed_at).toLocaleDateString() : 'Not observed';
      const fullRun = property.last_full_run;
      const fullRunDetails = fullRun
        ? `${when(fullRun.finished_at)} · ${fullRun.property_slug ? 'property run' : `all-properties run · ${fullRun.pages} pages total`}`
        : property.last_full_run_at ? when(property.last_full_run_at) : 'Not recorded';
      return <article className="coverage-card" key={property.property}><div className="coverage-card-head"><b>{property.name}</b><Status status={status} /></div><div className="coverage-counts">{property.review_count.toLocaleString()} stored {expected == null ? '· listing total unknown' : `/ ${expected.toLocaleString()} listed`}</div>{property.coverage_pct != null && <div className="coverage-meter"><span style={{ width: `${property.coverage_pct}%` }} /></div>}<div className="coverage-detail"><span>Snapshot coverage</span><b>{property.coverage_pct == null ? 'Not measured' : `${property.coverage_pct}%`}</b></div><div className="coverage-detail"><span>Remaining gap</span><b>{property.missing_count == null ? 'Unknown' : property.missing_count.toLocaleString()}</b></div><div className="coverage-detail"><span>Booking.com score</span><b>{property.booking_overall_score == null ? 'Not captured' : `${Number(property.booking_overall_score).toFixed(1)} / 10`}</b></div><div className="coverage-detail"><span>Listing snapshot date</span><b>{sourceDate}</b></div><div className="coverage-detail"><span>Last successful collection</span><b>{ago(property.success_age_hours)}</b></div><div className="coverage-detail"><span>Full backfill evidence</span><b>{fullRunDetails}</b></div><div className="coverage-run-state"><span>Latest attempt: <Status status={property.latest_attempt_status} error={property.latest_attempt_error} /></span>{property.latest_attempt_error && <p>{attemptMessage(property.latest_attempt_error)}</p>}</div></article>;
    })}</div><p className="coverage-caveat">The source totals are dated snapshots, not a live Booking.com feed. A near-total count does not prove every review was captured; a backfill is complete only after a full crawl reaches the observed total without errors.</p></section>

    <section className="panel business-impact"><div className="panel-head"><div><h2><Activity size={17} />Business Impact: Before vs After Corrective Actions</h2><p>Compares topic complaint frequency per 100 reviews, negative rate, and average rating around each action's completion date. This is descriptive and does not prove causation.</p></div><div className="impact-windows">{[14, 30, 60].map((days) => <button key={days} disabled={!impactAvailable} className={impactWindow === days ? 'active' : ''} onClick={() => onImpactWindowChange(days)}>{days}d window</button>)}</div></div>
      {impactAvailable && <div className="impact-stat-grid"><article><span>TRACKED ACTIONS</span><b>{impact.tracked_actions ?? 0}</b></article><article className="improved"><span>MEASURED IMPROVED</span><b>{impact.measured_improved ?? 0}</b></article><article className="worsened"><span>WORSENED / ESCALATED</span><b>{impact.worsened_or_escalated ?? 0}</b></article><article><span>AWAITING POST DATA</span><b>{impact.awaiting_post_data ?? 0}</b><small>{impact.awaiting_completion ?? 0} awaiting completion</small></article></div>}
      {!impactAvailable ? <div className="impact-empty backend-version-note"><AlertTriangle size={22} /><b>Restart the backend to load action impact data</b><span>The API currently serving this page predates before-and-after action measurements. Restart it to calculate these values from completed actions and stored reviews.</span></div> : data.impact_actions?.length ? <div className="impact-action-list">{data.impact_actions.map((action) => <article className={`impact-action ${action.status}`} key={action.id}><div className="impact-action-title"><span className="impact-outcome-icon">{action.status === 'improved' ? <TrendingDown size={16} /> : action.status === 'worsened' ? <TrendingUp size={16} /> : action.status === 'awaiting_post_data' || action.status === 'awaiting_action' ? <Clock3 size={16} /> : <Activity size={16} />}</span><div><b>{action.title}</b><small>{action.topic} · {action.property_slug === 'all' ? 'All properties' : action.property_slug} · {action.status.replaceAll('_', ' ')}</small></div></div>{action.before && action.after ? <div className="impact-comparison"><span>Topic mentions per 100 reviews <b>{action.before.topic_mentions_per_100 ?? '—'} → {action.after.topic_mentions_per_100 ?? '—'} ({action.topic_rate_change > 0 ? '+' : ''}{action.topic_rate_change})</b></span><span>Negative rate <b>{action.before.negative_rate ?? '—'}% → {action.after.negative_rate ?? '—'}%</b></span><span>Avg rating <b>{action.before.average ?? '—'} → {action.after.average ?? '—'}/10</b></span><small>Before {action.before_start}–{action.before_end} · after {action.after_start}–{action.after_end}</small></div> : <p className="impact-pending">{action.status === 'awaiting_action' ? 'Complete this action to begin the post-action measurement window.' : `Waiting for a full ${action.window_days || impactWindow}-day post-action window with review data.`}</p>}</article>)}</div> : <div className="impact-empty"><Activity size={22} /><b>No corrective actions have been tracked yet</b><span>Create and complete an action in Operations & Actions. This section will compare real review data from the periods before and after completion.</span></div>}
    </section>

    <section className="panel coverage-panel"><div className="panel-head"><div><h2><Activity size={17} />Property collection status</h2><p>Latest attempt and last successful sync are shown separately for each hotel.</p></div><Status status={overallStatus} /></div><div className="coverage-list">{properties.map((property) => {
      const status = property.latest_attempt_status || 'unknown';
      const iconStatus = property.health_status === 'healthy' ? 'success' : property.health_status === 'stale' ? 'error' : 'pending';
      return <article className="coverage-row" key={property.property}><div className={`coverage-icon ${iconStatus}`}>{property.health_status === 'healthy' ? <CheckCircle2 size={17} /> : property.health_status === 'stale' ? <CircleAlert size={17} /> : <Clock3 size={17} />}</div><div className="coverage-property"><b>{property.name}</b><span>{property.review_count.toLocaleString()} stored reviews · last success {ago(property.success_age_hours)}</span></div><div className="coverage-last"><small>Latest attempt</small><span>{when(property.latest_attempt_at)}</span></div><Status status={status} error={property.latest_attempt_error} /></article>;
    })}</div></section>

    <section className="panel run-history"><div className="panel-head"><div><h2><Clock3 size={17} />Recent collection runs</h2><p>Recent sync outcomes, with detailed errors available when needed.</p></div><button className="secondary-button" onClick={() => setShowRunHistory((shown) => !shown)} aria-expanded={showRunHistory}>{showRunHistory ? 'Hide' : 'View'} {data.recent_runs?.length || 0} recent runs · {historyErrors} recent issues</button></div>{data.recent_runs?.length ? showRunHistory ? <div className="run-table-wrap"><table className="run-table"><thead><tr><th>Started</th><th>Scope</th><th>Status</th><th>Pages</th><th>New</th><th>Duplicates</th></tr></thead><tbody>{data.recent_runs.map((run) => <tr key={run.id}><td>{when(run.started_at)}</td><td>{run.property_slug || 'All properties'}</td><td><Status status={run.status} error={run.errors} />{run.errors && <details className="run-error-detail"><summary>View run errors</summary><pre>{run.errors}</pre></details>}</td><td>{run.pages}</td><td>{run.new_reviews}</td><td>{run.duplicates_skipped}</td></tr>)}</tbody></table></div> : <div className="run-history-summary"><span>Most recent attempt: <Status status={data.recent_runs[0].status} error={data.recent_runs[0].errors} /> · {when(data.recent_runs[0].started_at)}</span><span>{activeRuns} active runs · {historyErrors} of the latest 5 runs reported issues</span></div> : <div className="empty"><Clock3 size={26} /><b>No scrape runs recorded</b><span>Use Run incremental sync to start a collection.</span></div>}</section>

    <div className="impact-note"><span>{ratingChange > 0 ? <ArrowUpRight size={17} /> : <ArrowDownRight size={17} />}</span><p><b>How to read the comparisons:</b> Collector health uses the last successful run; the latest attempt is still shown separately. Business impact compares review patterns around completed actions and cannot attribute changes to an action by itself.</p></div>
  </div>;
}
