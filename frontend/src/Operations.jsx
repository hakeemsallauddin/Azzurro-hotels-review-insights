import React, { useState } from 'react';
import { AlertTriangle, ArrowRight, Check, ClipboardCheck, Plus, ThumbsUp, Wrench } from 'lucide-react';

const TOPICS = ['Cleanliness', 'Check-in experience', 'Staff behaviour', 'Noise', 'Facilities', 'Location', 'Room condition', 'Value for money'];
const DEPARTMENTS = ['Housekeeping', 'Front desk', 'Maintenance', 'Guest relations', 'Management'];
const DEPARTMENT_FOR_TOPIC = {
  Cleanliness: 'Housekeeping', 'Check-in experience': 'Front desk', 'Staff behaviour': 'Guest relations',
  Noise: 'Maintenance', Facilities: 'Maintenance', Location: 'Management', 'Room condition': 'Maintenance', 'Value for money': 'Management',
};
const API = '/api';

async function send(path, method, body) {
  const response = await fetch(`${API}${path}`, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error || `API ${response.status}`);
  return data;
}

function ActionForm({ issue, property, onCancel, onSaved }) {
  const [topic, setTopic] = useState(issue?.topic || TOPICS[0]);
  const [title, setTitle] = useState(issue ? `Address recurring ${issue.topic.toLowerCase()} feedback` : '');
  const [details, setDetails] = useState(issue ? `${issue.review_count} negative reviews mentioned this topic during the 30-day review window.` : '');
  const [department, setDepartment] = useState(DEPARTMENT_FOR_TOPIC[issue?.topic || TOPICS[0]]);
  const [priority, setPriority] = useState(issue?.severity === 'high' ? 'high' : 'medium');
  const [owner, setOwner] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function submit(event) {
    event.preventDefault(); setSaving(true); setError('');
    try {
      await send('/actions', 'POST', { title, details, topic, property_slug: issue?.property || property || 'all', department, priority, owner, due_date: dueDate || null });
      await onSaved();
    } catch (exception) { setError(exception.message); }
    finally { setSaving(false); }
  }

  return <form className="action-form" onSubmit={submit}>
    <div className="form-heading"><div><span className="eyebrow">ACTION PLAN</span><h3>{issue ? `Create action · ${issue.topic}` : 'Create an operational action'}</h3><p>Assign an owner and due date so the follow-up is visible to the team.</p></div></div>
    <div className="form-grid"><label>Action title<input required minLength="3" maxLength="160" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Review bathroom cleaning checks" /></label><label>Operational topic<select value={topic} onChange={(event) => { setTopic(event.target.value); setDepartment(DEPARTMENT_FOR_TOPIC[event.target.value]); }} disabled={Boolean(issue)}>{TOPICS.map((item) => <option key={item}>{item}</option>)}</select></label><label>Department<select value={department} onChange={(event) => setDepartment(event.target.value)}>{DEPARTMENTS.map((item) => <option key={item}>{item}</option>)}</select></label><label>Priority<select value={priority} onChange={(event) => setPriority(event.target.value)}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></label><label>Owner<input maxLength="120" value={owner} onChange={(event) => setOwner(event.target.value)} placeholder="Assign a team member" /></label><label>Due date<input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} /></label><label className="span-two">Details<textarea maxLength="2000" rows="3" value={details} onChange={(event) => setDetails(event.target.value)} placeholder="Describe the follow-up or operational change" /></label></div>
    {error && <div className="inline-error" role="alert">{error}</div>}
    <div className="form-actions"><button type="button" className="secondary-button" onClick={onCancel}>Cancel</button><button className="primary" disabled={saving}>{saving ? 'Saving…' : 'Create action'}</button></div>
  </form>;
}

export default function Operations({ data, property, onChanged, onInspectTopic }) {
  const [issueForForm, setIssueForForm] = useState(undefined);
  const [updating, setUpdating] = useState('');
  const [error, setError] = useState('');
  const issues = data?.issues ?? [];
  const praises = data?.praises ?? [];
  const actions = data?.actions ?? [];
  const openActions = actions.filter((action) => action.status !== 'completed');
  const highIssues = issues.filter((issue) => issue.severity === 'high').length;

  if (!data) return <div className="tab-content"><section className="panel empty"><ClipboardCheck size={28} /><b>Operations data is not connected</b><span>Restart the backend API so it can create the action table and serve recurring issue summaries.</span></section></div>;

  async function updateStatus(action, status) {
    setUpdating(action.id); setError('');
    try { await send(`/actions/${action.id}`, 'PATCH', { status }); await onChanged(); }
    catch (exception) { setError(exception.message); }
    finally { setUpdating(''); }
  }

  return <div className="tab-content">
    <section className="page-intro"><div><span className="eyebrow">30-DAY OPERATING WINDOW · {data?.window_start || '—'} TO {data?.reference_date || '—'}</span><h2>Recurring issues and action tracking</h2><p>Issues come from negative review text. Create a follow-up, assign a department, and track it until the work is complete.</p></div><button className="primary" onClick={() => setIssueForForm(null)}><Plus size={16} />New action</button></section>
    <section className="ops-summary"><article className="summary-card"><span>RECURRING TOPICS</span><strong>{issues.length}</strong><small>With negative mentions in this period</small></article><article className="summary-card tone-red"><span>HIGH-VOLUME TOPICS</span><strong>{highIssues}</strong><small>10 or more negative reviews</small></article><article className="summary-card tone-blue"><span>OPEN ACTIONS</span><strong>{openActions.length}</strong><small>Assigned or awaiting work</small></article><article className="summary-card tone-green"><span>COMPLETED</span><strong>{actions.length - openActions.length}</strong><small>Tracked actions completed</small></article></section>

    {issueForForm !== undefined && <ActionForm issue={issueForForm || null} property={property} onCancel={() => setIssueForForm(undefined)} onSaved={async () => { setIssueForForm(undefined); await onChanged(); }} />}
    {error && <div className="error" role="alert">{error}</div>}

    <section className="panel issue-panel"><div className="panel-head"><div><h2><AlertTriangle size={17} />Recurring issue signals</h2><p>Counts and quoted examples come from negative review text in this window. Select a review to open the matching feed.</p></div><span className="window-pill">Last {data.days} days · {data.period_review_count.toLocaleString()} reviews</span></div>
      {issues.length ? <div className="issue-grid">{issues.map((issue) => <article className={`issue-card ${issue.severity}`} key={issue.topic}><div className="issue-card-top"><div className="issue-icon"><Wrench size={17} /></div><span className={`severity ${issue.severity}`}>{issue.severity === 'high' ? 'High volume' : issue.severity === 'watch' ? 'Watch' : 'Emerging'}</span></div><h3>{issue.topic}</h3><div className="issue-metrics"><span><b>{issue.review_count}</b>negative reviews</span><span><b>{issue.negative_share}%</b>of negative feedback</span><span><b>{issue.low_rating_count}</b>rated under 7</span><span><b>{issue.average_rating ?? '—'}/10</b>mean score</span></div><div className="issue-properties">{issue.properties.map((place) => <span key={place.slug}>{place.name}<b>{place.reviews}</b></span>)}</div>{issue.examples?.length > 0 && <div className="issue-examples">{issue.examples.map((review) => <div key={review.review_id}><b>{review.property_name} · {review.rating}/10 · {review.review_date}</b><span>{review.negative_text || review.title || 'No review text provided'}</span></div>)}</div>}<div className="issue-actions"><button className="text-action" onClick={() => onInspectTopic(issue.topic, 'negative')}>View matching reviews <ArrowRight size={14} /></button><button className="text-action" onClick={() => setIssueForForm(issue)}>Create action <ArrowRight size={14} /></button></div></article>)}</div> : <div className="empty"><Check size={28} /><b>No recurring negative topic signals</b><span>No topic appeared in negative reviews during this window.</span></div>}
    </section>

    <section className="panel praise-panel"><div className="panel-head"><div><h2><ThumbsUp size={17} />Guest praise signals</h2><p>Positive themes and excerpts come from positive review text in the same operating window.</p></div><span className="window-pill">{data.positive_review_count.toLocaleString()} positive reviews</span></div>{praises.length ? <div className="praise-grid">{praises.map((praise) => <article className="praise-card" key={praise.topic}><div className="praise-card-top"><div className="praise-icon"><ThumbsUp size={16} /></div><span>{praise.positive_share}% of positive feedback</span></div><h3>{praise.topic}</h3><p>{praise.review_count} positive reviews · {praise.average_rating ?? '—'}/10 average</p><div className="issue-properties">{praise.properties.map((place) => <span key={place.slug}>{place.name}<b>{place.reviews}</b></span>)}</div>{praise.examples?.length > 0 && <div className="praise-examples">{praise.examples.map((review) => <div key={review.review_id}><b>{review.property_name} · {review.rating}/10 · {review.review_date}</b><span>{review.positive_text || review.title || 'No review text provided'}</span></div>)}</div>}<button className="text-action" onClick={() => onInspectTopic(praise.topic, 'positive')}>View praise reviews <ArrowRight size={14} /></button></article>)}</div> : <div className="empty"><ThumbsUp size={26} /><b>No tagged praise themes in this window</b><span>Positive comments are only tagged when review text contains a recognized topic.</span></div>}</section>

    <section className="panel action-panel"><div className="panel-head"><div><h2><ClipboardCheck size={17} />Operations action tracker</h2><p>Actions are stored in the local review database and remain available after restart.</p></div></div>
      {actions.length ? <div className="action-list">{actions.map((action) => <article className={`action-row ${action.status}`} key={action.id}><div className="action-priority"><span className={`priority-dot ${action.priority}`} />{action.priority}</div><div className="action-main"><h3>{action.title}</h3><p>{action.details || 'No additional details'} </p><div className="action-meta"><span>{action.topic}</span><span>{action.property_slug === 'all' ? 'All properties' : action.property_slug}</span><span>{action.department}</span>{action.owner && <span>Owner: {action.owner}</span>}{action.due_date && <span>Due {action.due_date}</span>}</div>{action.status === 'completed' && action.completion_note && <p className="completion-note">Completion note: {action.completion_note}</p>}</div><label className="status-control">Status<select value={action.status} disabled={updating === action.id} onChange={(event) => updateStatus(action, event.target.value)}><option value="open">Open</option><option value="in_progress">In progress</option><option value="completed">Completed</option></select></label></article>)}</div> : <div className="empty"><ClipboardCheck size={28} /><b>No operational actions yet</b><span>Create an action from a recurring topic to assign follow-up work.</span></div>}
    </section>
  </div>;
}
