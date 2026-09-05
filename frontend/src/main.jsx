import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function Metric({ label, value }) {
  return <article className="metric"><small>{label}</small><strong>{String(value ?? 'Not detected')}</strong></article>;
}

function App() {
  const [url, setUrl] = useState('https://github.com/fastapi/fastapi');
  const [data, setData] = useState(null);
  const [tab, setTab] = useState('overview');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function analyze() {
    setLoading(true);
    setError('');
    setData(null);
    try {
      const res = await fetch(`${API}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: url })
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Analysis failed');
      setData(body);
    } catch (err) {
      setError(err.message || 'Analysis failed');
    } finally {
      setLoading(false);
    }
  }

  const s = data?.summary;

  return (
    <div className="app">
      <header className="header">
        <div>
          <span className="badge">NO AI API REQUIRED</span>
          <h1>Repository Intelligence</h1>
          <p>GitHub repository → evidence-backed stack detection → deployment IR → Docker artifacts.</p>
        </div>
        <div className="logo">AD</div>
      </header>

      <main>
        <section className="hero panel">
          <label>GitHub repository URL</label>
          <div className="input-row">
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/owner/repo" />
            <button onClick={analyze} disabled={loading}>{loading ? 'Scanning…' : 'Analyze repository'}</button>
          </div>
          <div className="hint">The engine scans manifests, lockfiles, source/configuration signals, CI/CD files, infrastructure hints, services, ports and environment references.</div>
          {error && <div className="error">{error}</div>}
        </section>

        {!data && !loading && <section className="panel intro"><h2>What this prototype detects</h2><p>Languages, runtime versions, package managers, frameworks, databases, caches, queues, cloud integrations, workers, schedulers, monorepos, CI/CD, health endpoints, environment variables and existing deployment files.</p></section>}
        {loading && <section className="panel loading"><div className="loader" /> <div><h2>Analyzing repository</h2><p>Reading repository evidence and building a deployment model.</p></div></section>}

        {data && <>
          <nav className="tabs">
            {['overview','evidence','ir','files'].map((key) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{key === 'ir' ? 'Deployment IR' : key === 'files' ? 'Generated files' : key[0].toUpperCase() + key.slice(1)}</button>)}
          </nav>

          {tab === 'overview' && <>
            <section className="grid">
              <Metric label="Primary language" value={s.language} />
              <Metric label="Runtime" value={`${s.runtime} ${s.runtime_version}`} />
              <Metric label="Framework" value={s.framework} />
              <Metric label="Package manager" value={`${s.package_manager}${s.package_manager_version !== 'Not declared' ? ` ${s.package_manager_version}` : ''}`} />
              <Metric label="Build command" value={s.build_command} />
              <Metric label="Start command" value={s.start_command} />
              <Metric label="Port" value={s.port} />
              <Metric label="Confidence" value={`${s.confidence}%`} />
            </section>
            <section className="split">
              <div className="panel"><h2>Architecture signals</h2><div className="chips">{s.application_roles.map((x) => <span key={x}>{x}</span>)}{s.monorepo && <span>monorepo</span>}{s.health_endpoint !== 'Not detected' && <span>health: {s.health_endpoint}</span>}</div><p className="muted">Services: {s.services.length ? s.services.join(', ') : 'None detected'}</p><p className="muted">CI/CD: {s.ci_signals.length ? s.ci_signals.join(', ') : 'No strong CI/CD signal'}</p></div>
              <div className="panel"><h2>Language candidates</h2>{s.language_candidates.map((x) => <div className="candidate" key={x.name}><span>{x.name}</span><b>{x.score}</b></div>)}</div>
            </section>
            <section className="panel"><h2>Generated deployment shape</h2><div className="arch"><div className="arch-node">Internet</div><span>↓</span><div className="arch-node">Application<br/><small>{s.framework} · port {s.port || '?'}</small></div>{s.services.length > 0 && <><span>↓</span><div className="services">{s.services.map((x) => <div key={x}>{x}</div>)}</div></>}</div></section>
          </>}

          {tab === 'evidence' && <section className="panel"><h2>Evidence ledger</h2><p className="muted">Detections are backed by repository evidence rather than a black-box answer.</p>{data.evidence.map((e, i) => <div className="evidence" key={`${e.file}-${i}`}><b>{e.points}</b><div><strong>{e.category} · {e.file}</strong><p>{e.reason}</p></div></div>)}</section>}

          {tab === 'ir' && <section className="panel"><h2>Deployment IR</h2><pre>{JSON.stringify(data.deployment_ir, null, 2)}</pre></section>}

          {tab === 'files' && <div className="files">{Object.entries(data.generated_files).map(([name, content]) => <section className="panel" key={name}><h2>{name}</h2><pre>{content}</pre></section>)}</div>}
        </>}
      </main>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
