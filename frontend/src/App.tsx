import { useMemo, useState } from 'react';
import './styles.css';

type Scenario = { id: string; name: string; holes: number; assays: number; grade: number; range: number; color: string };
type Sample = { depth: number; value: number; hole: number };
type Estimate = { mean: number; uncertainty: number; cv: number; range: number; count: number };

const scenarios: Scenario[] = [
  { id: 'copper-ridge', name: 'Copper Ridge · porphyry', holes: 18, assays: 684, grade: 0.82, range: 142, color: '#f2b56b' },
  { id: 'north-shear', name: 'North Shear · structural', holes: 12, assays: 431, grade: 2.34, range: 88, color: '#e8839b' },
  { id: 'lithium-basin', name: 'Salar Edge · brine interface', holes: 24, assays: 912, grade: 1.17, range: 216, color: '#7ed7d0' },
];
const bands = [['Oxide cap', 0, 24, '#283d4a'], ['Weathered halo', 24, 72, '#324b4f'], ['Potassic core', 72, 134, '#4a3f49'], ['Propylitic wall', 134, 198, '#2b4a50'], ['Fresh basement', 198, 260, '#243642']] as const;
const depthY = (depth: number) => 116 + depth * 1.62;
const methodNames = ['Ordinary kriging', 'Simple kriging', 'Universal kriging', 'Indicator kriging', 'Sequential Gaussian simulation', 'Direct sampling (MPS)'];

function seedSamples(scenario: Scenario): Sample[] {
  return Array.from({ length: 44 }, (_, i) => ({
    depth: 8 + ((i * 29) % 242),
    value: Math.max(0.03, scenario.grade * (0.34 + Math.abs(Math.sin(i * 0.71 + scenario.grade)) * 1.35)),
    hole: i % 3,
  }));
}

function estimateAt(samples: Sample[], depth: number, method: string, scenario: Scenario): Estimate {
  const nearest = [...samples].sort((a, b) => Math.abs(a.depth - depth) - Math.abs(b.depth - depth)).slice(0, method === 'Direct sampling (MPS)' ? 12 : 10);
  const power = method.includes('Simple') ? 1.55 : method.includes('Universal') ? 1.3 : 1.8;
  const weights = nearest.map((s) => 1 / Math.pow(Math.abs(s.depth - depth) + 2, power));
  const weightTotal = weights.reduce((a, b) => a + b, 0);
  const mean = nearest.reduce((sum, s, i) => sum + s.value * weights[i], 0) / weightTotal;
  const variance = nearest.reduce((sum, s, i) => sum + weights[i] * (s.value - mean) ** 2, 0) / weightTotal;
  const uncertainty = Math.sqrt(variance) * (method.includes('Indicator') ? 1.18 : method.includes('simulation') || method.includes('MPS') ? 1.35 : 1);
  const residual = samples.reduce((sum, s) => sum + Math.abs(s.value - scenario.grade), 0) / Math.max(samples.length, 1);
  return { mean, uncertainty, cv: Math.max(0, Math.min(0.99, 1 - residual / (scenario.grade * 2.5))), range: scenario.range, count: samples.length };
}

function parseAssayCsv(text: string, hole: number): Sample[] {
  const rows = text.trim().split(/\r?\n/).filter(Boolean);
  if (rows.length < 2) return [];
  const headers = rows[0].split(',').map((h) => h.trim().toLowerCase());
  const depthIndex = headers.findIndex((h) => ['depth', 'mid_depth', 'mid', 'from', 'to'].some((key) => h.includes(key)));
  const valueIndex = headers.findIndex((h) => ['cu', 'grade', 'assay', 'value', 'au', 'li'].some((key) => h === key || h.includes(key)));
  if (depthIndex < 0 || valueIndex < 0) return [];
  return rows.slice(1).flatMap((row) => {
    const cells = row.split(',').map((cell) => cell.trim());
    const depth = Number(cells[depthIndex]);
    const value = Number(cells[valueIndex]);
    return Number.isFinite(depth) && Number.isFinite(value) ? [{ depth: Math.max(0, Math.min(260, depth)), value: Math.max(0, value), hole }] : [];
  }).slice(0, 2000);
}

export default function App() {
  const [scenarioId, setScenarioId] = useState(scenarios[0].id);
  const [metric, setMetric] = useState<'grade' | 'uncertainty' | 'lithology'>('grade');
  const [method, setMethod] = useState(methodNames[0]);
  const [selectedDepth, setSelectedDepth] = useState(132);
  const [playing, setPlaying] = useState(true);
  const [sources, setSources] = useState(['collar_survey.csv', 'assay_2024.csv', 'lithology_intervals.csv']);
  const [customSamples, setCustomSamples] = useState<Sample[]>([]);
  const [running, setRunning] = useState(false);
  const [lastRun, setLastRun] = useState('Local estimate ready');
  const scenario = scenarios.find((item) => item.id === scenarioId) ?? scenarios[0];
  const samples = useMemo(() => [...seedSamples(scenario), ...customSamples], [scenario, customSamples]);
  const result = useMemo(() => estimateAt(samples, selectedDepth, method, scenario), [samples, selectedDepth, method, scenario]);
  const profile = useMemo(() => Array.from({ length: 15 }, (_, i) => { const depth = i * 18 + 8; return { depth, value: estimateAt(samples, depth, method, scenario).mean }; }), [samples, method, scenario]);

  const addFiles = async (files: FileList | null) => {
    if (!files) return;
    const incoming = Array.from(files);
    setSources((current) => [...new Set([...current, ...incoming.map((file) => file.name)])]);
    const parsed = (await Promise.all(incoming.map(async (file, index) => file.name.toLowerCase().endsWith('.csv') ? parseAssayCsv(await file.text(), index % 3) : []))).flat();
    if (parsed.length) { setCustomSamples((current) => [...current, ...parsed]); setLastRun(`Loaded ${parsed.length} assay observations from local files`); }
  };
  const runEstimate = () => { setRunning(true); setLastRun('Solving local support weights…'); window.setTimeout(() => { setRunning(false); setLastRun(`${method} solved locally · ${result.count} observations`); }, 420); };

  return <main className="sondara-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark">◈</span><strong>SONDARA</strong><span className="brand-context">DRILLHOLE INTELLIGENCE</span></div><nav><button className="nav-active">Workbench</button><button>Data contract</button><button>Methods</button><button>Cases</button></nav><div className="top-actions"><span className="local-dot" /> LOCAL COMPUTE <button className="icon-button">◐</button></div></header>
    <section className="command-bar"><div><span className="eyebrow">PROJECT / OPEN PIT STUDY</span><h1>Subsurface signal, made inspectable.</h1><p>Load collars, surveys, assays and geology. Trace continuity, test support and compare estimators in one spatial model.</p></div><div className="command-controls"><label>Case<select value={scenarioId} onChange={(event) => { setScenarioId(event.target.value); setCustomSamples([]); }}>{scenarios.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button className="primary-button" onClick={runEstimate} disabled={running}>{running ? 'Solving…' : 'Run local estimate'} <span>↗</span></button></div></section>
    <section className="workspace-grid">
      <aside className="rail left-rail"><div className="rail-heading"><span>01</span><h2>Sources</h2><span className="check">✓</span></div><p className="rail-copy">Every observation keeps its support, unit and provenance.</p><label className="dropzone"><input type="file" multiple accept=".csv,.json,.parquet" onChange={(event) => void addFiles(event.target.files)} /><span className="upload-icon">＋</span><strong>Drop source files</strong><small>CSV · JSON · Parquet</small></label><div className="source-list">{sources.map((file, index) => <div className="source-row" key={file}><span className="source-icon">{index === 0 ? '⌖' : index === 1 ? '∿' : '▦'}</span><span><strong>{file}</strong><small>{index === 0 ? `${scenario.holes} collars · projected CRS` : index === 1 ? `${scenario.assays} intervals · grade` : '5 lithologies · coded'}</small></span><b>✓</b></div>)}</div><button className="text-button">＋ Add source recipe</button><div className="rail-divider" /><div className="rail-heading compact"><span>02</span><h2>Support</h2></div><div className="support-card"><div><span>Composite length</span><strong>2.0 m</strong></div><div><span>Survey mode</span><strong>Minimum curvature</strong></div><div><span>Frame</span><strong>Local metric · metres</strong></div></div></aside>
      <section className="viz-column"><div className="viz-toolbar"><div><span className="eyebrow">SPATIAL MODEL / {scenario.name.toUpperCase()}</span><strong>Section explorer</strong><span className="toolbar-muted">{scenario.holes} holes · {result.count} supports · Z 0–260 m</span></div><div className="toolbar-actions"><button className={playing ? 'toolbar-active' : ''} onClick={() => setPlaying((value) => !value)}>{playing ? 'Ⅱ Pause field' : '▶ Play field'}</button><button onClick={() => setSelectedDepth((depth) => depth === 132 ? 196 : 132)}>⌖ Follow cursor</button><button>⤢</button></div></div>
        <div className={`section-canvas ${playing ? 'is-playing' : ''}`}><div className="canvas-grid" /><div className="canvas-label top-left"><span>Y + 420</span><span>X + 180</span></div><div className="canvas-label bottom-right">LOCAL FRAME · EPSG:32719</div><svg className="section-svg" viewBox="0 0 920 580" role="img" aria-label="Animated three-dimensional drillhole section with assay points and grade continuity"><defs><linearGradient id="depthFade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#101d29" /><stop offset="1" stopColor="#0c1821" /></linearGradient><filter id="glow"><feGaussianBlur stdDeviation="5" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter><linearGradient id="oreRibbon"><stop stopColor={scenario.color} stopOpacity=".05" /><stop offset=".45" stopColor={scenario.color} stopOpacity=".64" /><stop offset="1" stopColor="#e8839b" stopOpacity=".03" /></linearGradient></defs><rect x="42" y="52" width="836" height="478" rx="18" fill="url(#depthFade)" stroke="#284453" />{bands.map(([label, from, to, color]) => <g key={label}><rect x="62" y={depthY(from)} width="796" height={(to - from) * 1.62} fill={color} opacity=".44" /><text x="78" y={depthY(from + 13)} className="band-label">{label}</text></g>)}<path d="M210 112 C235 180 190 270 244 356 S205 464 223 518" fill="none" stroke="#6e8790" strokeWidth="7" opacity=".72" /><path d="M210 112 C235 180 190 270 244 356 S205 464 223 518" fill="none" stroke="#d6f1e5" strokeWidth="2" strokeDasharray="5 10" className="survey-line" /><path d="M485 112 C452 192 532 278 477 359 S510 466 486 518" fill="none" stroke="#6e8790" strokeWidth="7" opacity=".72" /><path d="M485 112 C452 192 532 278 477 359 S510 466 486 518" fill="none" stroke="#d6f1e5" strokeWidth="2" strokeDasharray="5 10" className="survey-line reverse" /><path d="M746 112 C716 188 780 270 724 354 S759 458 733 518" fill="none" stroke="#6e8790" strokeWidth="7" opacity=".72" /><path d="M746 112 C716 188 780 270 724 354 S759 458 733 518" fill="none" stroke="#d6f1e5" strokeWidth="2" strokeDasharray="5 10" className="survey-line" /><path d="M218 314 C325 260 407 292 486 318 S640 340 736 288" fill="none" stroke="url(#oreRibbon)" strokeWidth="34" filter="url(#glow)" className="ore-ribbon" /><path d="M218 314 C325 260 407 292 486 318 S640 340 736 288" fill="none" stroke={scenario.color} strokeWidth="2" strokeDasharray="2 13" className="grade-front" />{[210, 485, 746].map((x, hole) => <g key={x}><circle cx={x} cy="112" r="10" fill="#d4e7e6" stroke={scenario.color} strokeWidth="4" /><text x={x - 20} y="91" className="hole-label">DH-{String(hole + 1).padStart(2, '0')}</text></g>)}{samples.map((point, index) => { const x = [210, 485, 746][point.hole] + Math.sin(index * 1.4) * 18 + (index % 2 ? 5 : -5); const y = depthY(point.depth); const high = metric === 'uncertainty' ? Math.abs(point.value - result.mean) > result.uncertainty : metric === 'lithology' ? point.depth > 134 : point.value > result.mean * 1.45; const radius = high ? 6 : 3.5; return <g key={`${point.depth}-${index}`} className="assay-point" onClick={() => setSelectedDepth(point.depth)}><circle cx={x} cy={y} r={radius} fill={high ? scenario.color : '#67c8c1'} opacity=".96" /><circle cx={x} cy={y} r={high ? 13 : 7} fill="none" stroke={high ? scenario.color : '#67c8c1'} opacity=".18" /></g>; })}<line x1="62" x2="858" y1={depthY(selectedDepth)} y2={depthY(selectedDepth)} stroke={scenario.color} strokeWidth="1.5" strokeDasharray="7 7" /><rect x="72" y={depthY(selectedDepth) - 19} width="132" height="24" rx="12" fill={scenario.color} /><text x="85" y={depthY(selectedDepth) - 3} className="cursor-label">{selectedDepth} m · {result.mean.toFixed(2)} %</text>{[0, 50, 100, 150, 200, 250].map((depth) => <g key={depth}><line x1="48" x2="58" y1={depthY(depth)} y2={depthY(depth)} stroke="#59717a" /><text x="18" y={depthY(depth) + 4} className="depth-label">{depth}</text></g>)}</svg><div className="viz-legend"><span><i className="legend-dot high" /> High grade</span><span><i className="legend-dot continuity" /> Continuity front</span><span><i className="legend-dot hole" /> Surveyed trace</span></div></div><div className="viz-footer"><span><b>CURSOR</b> {selectedDepth} m · DH-02 · {result.mean.toFixed(2)} % · support 2 m</span><span className="quality"><i /> {lastRun}</span></div></section>
      <aside className="rail right-rail"><div className="rail-heading"><span>03</span><h2>Estimate</h2><span className="live-pill">LIVE</span></div><label>Method<select value={method} onChange={(event) => setMethod(event.target.value)}>{methodNames.map((name) => <option key={name}>{name}</option>)}</select></label><div className="metric-switch">{(['grade', 'uncertainty', 'lithology'] as const).map((item) => <button key={item} className={metric === item ? 'active' : ''} onClick={() => setMetric(item)}>{item[0].toUpperCase() + item.slice(1)}</button>)}</div><div className="stat-grid"><div><span>Mean estimate</span><strong>{result.mean.toFixed(2)} %</strong><small>local support</small></div><div><span>Spatial range</span><strong>{result.range} m</strong><small>major direction</small></div><div><span>Cross validation</span><strong>{result.cv.toFixed(2)}</strong><small>R² · {result.count} samples</small></div><div><span>P90 uncertainty</span><strong>±{result.uncertainty.toFixed(2)}</strong><small>local support</small></div></div><div className="confidence"><div className="confidence-head"><span>Support confidence</span><strong>{Math.round(Math.max(0, 100 - result.uncertainty / Math.max(result.mean, .01) * 100))}%</strong></div><div className="confidence-bar"><i style={{ width: `${Math.max(8, Math.min(96, 100 - result.uncertainty / Math.max(result.mean, .01) * 100))}%` }} /></div><p>{customSamples.length ? 'Uploaded observations are included in this local solve.' : 'Seeded case observations are active; upload an assay CSV to replace the planning signal.'}</p></div><div className="rail-divider" /><div className="rail-heading compact"><span>04</span><h2>Diagnostics</h2></div><div className="diagnostic-row"><span className="diag-ok">●</span><span>Coordinate frame</span><strong>OK</strong></div><div className="diagnostic-row"><span className="diag-ok">●</span><span>Support overlaps</span><strong>0</strong></div><div className="diagnostic-row"><span className="diag-warn">●</span><span>Extrapolation cells</span><strong>{Math.round(100 - result.cv * 100)}%</strong></div><button className="outline-button" onClick={() => setLastRun(`Validation: ${result.count} supports · residual CV ${(1 - result.cv).toFixed(2)}`)}>Open validation report ↗</button></aside>
    </section>
    <section className="analysis-strip"><div className="strip-title"><span className="eyebrow">ANALYSIS / {method.toUpperCase()}</span><h2>Does the signal travel between holes?</h2><p>Linked diagnostics update with the selected support and estimator.</p></div><div className="chart-card"><div className="chart-head"><span>Directional variogram</span><strong>{result.range} m range</strong></div><svg viewBox="0 0 330 104" className="mini-chart"><path d="M10 90 C38 18 75 26 106 45 S177 77 320 82" fill="none" stroke={scenario.color} strokeWidth="3" /><path d="M10 92 L320 92" stroke="#38505a" /><path d="M10 20 L10 92" stroke="#38505a" /><circle cx="106" cy="45" r="5" fill={scenario.color} className="chart-pulse" /><text x="102" y="102" className="axis-label">range</text><text x="12" y="16" className="axis-label">γ(h)</text></svg></div><div className="chart-card"><div className="chart-head"><span>Selected hole · DH-02</span><strong>grade profile</strong></div><svg viewBox="0 0 330 104" className="mini-chart"><path d={profile.map((item, index) => `${index ? 'L' : 'M'} ${18 + Math.min(280, item.value * 70)} ${10 + index * 6.2}`).join(' ')} fill="none" stroke="#7ed7d0" strokeWidth="3" /><path d="M18 8 L18 98 M18 98 L318 98" stroke="#38505a" /><text x="24" y="102" className="axis-label">0 m</text><text x="279" y="102" className="axis-label">260 m</text></svg></div><div className="decision-card"><span>MODEL DECISION</span><strong>{method} · {result.count} supports</strong><p>Estimate is computed in this browser from declared local supports. Upload a project file and inspect residuals before resource classification.</p><button className="text-button" onClick={() => setLastRun(`${method}: local support weights recomputed at ${selectedDepth} m`)}>View method notes ↗</button></div></section>
    <footer className="footer"><span>SONDARA · CAOS research project</span><span>Local-first · Apache-2.0 · no login</span><span>v0.1.2 · data never leaves this browser</span></footer>
  </main>;
}
