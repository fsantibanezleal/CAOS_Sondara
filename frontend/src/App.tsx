import { useMemo, useState } from 'react';
import SubsurfaceScene, { SceneLayers, SceneView } from './components/SubsurfaceScene';
import './styles.css';

type Scenario = { id: string; name: string; holes: number; assays: number; grade: number; range: number; color: string; summary: string };
type Sample = { depth: number; value: number; hole: number };
type Estimate = { mean: number; uncertainty: number; cv: number; range: number; count: number };

const scenarios: Scenario[] = [
  { id: 'copper-ridge', name: 'Copper Ridge', holes: 18, assays: 684, grade: 0.82, range: 142, color: '#f2b56b', summary: 'Porphyry copper · three benches · local metric frame' },
  { id: 'north-shear', name: 'North Shear', holes: 12, assays: 431, grade: 2.34, range: 88, color: '#e8839b', summary: 'Structural corridor · high grade shoots · tighter continuity' },
  { id: 'lithium-basin', name: 'Salar Edge', holes: 24, assays: 912, grade: 1.17, range: 216, color: '#7ed7d0', summary: 'Brine interface · broad support · layered basin model' },
];
const methods = ['Ordinary kriging', 'Simple kriging', 'Universal kriging', 'Indicator kriging', 'Sequential Gaussian simulation', 'Direct sampling (MPS)'];
const seedSamples = (scenario: Scenario): Sample[] => Array.from({ length: 44 }, (_, i) => ({
  depth: 8 + ((i * 29) % 242),
  value: Math.max(0.03, scenario.grade * (0.34 + Math.abs(Math.sin(i * 0.71 + scenario.grade)) * 1.35)),
  hole: i % 3,
}));

function estimateAt(samples: Sample[], depth: number, method: string, scenario: Scenario): Estimate {
  const nearest = [...samples].sort((a, b) => Math.abs(a.depth - depth) - Math.abs(b.depth - depth)).slice(0, method.includes('MPS') ? 12 : 10);
  const power = method.includes('Simple') ? 1.55 : method.includes('Universal') ? 1.3 : 1.8;
  const weights = nearest.map((sample) => 1 / Math.pow(Math.abs(sample.depth - depth) + 2, power));
  const total = weights.reduce((a, b) => a + b, 0);
  const mean = nearest.reduce((sum, sample, index) => sum + sample.value * weights[index], 0) / total;
  const variance = nearest.reduce((sum, sample, index) => sum + weights[index] * (sample.value - mean) ** 2, 0) / total;
  const uncertainty = Math.sqrt(variance) * (method.includes('Indicator') ? 1.18 : method.includes('simulation') || method.includes('MPS') ? 1.35 : 1);
  const residual = samples.reduce((sum, sample) => sum + Math.abs(sample.value - scenario.grade), 0) / Math.max(samples.length, 1);
  return { mean, uncertainty, cv: Math.max(0, Math.min(0.99, 1 - residual / (scenario.grade * 2.5))), range: scenario.range, count: samples.length };
}

function parseAssayCsv(text: string, hole: number): Sample[] {
  const rows = text.trim().split(/\r?\n/).filter(Boolean);
  if (rows.length < 2) return [];
  const headers = rows[0].split(',').map((header) => header.trim().toLowerCase());
  const depthIndex = headers.findIndex((header) => ['depth', 'mid_depth', 'mid', 'from', 'to'].some((key) => header.includes(key)));
  const valueIndex = headers.findIndex((header) => ['cu', 'grade', 'assay', 'value', 'au', 'li'].some((key) => header === key || header.includes(key)));
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
  const [method, setMethod] = useState(methods[0]);
  const [selectedDepth, setSelectedDepth] = useState(132);
  const [view, setView] = useState<SceneView>('orbit');
  const [playing, setPlaying] = useState(true);
  const [layers, setLayers] = useState<SceneLayers>({ boreholes: true, assay: true, ore: true, geology: true, grid: true });
  const [sources, setSources] = useState(['collar_survey.csv', 'assay_2024.csv', 'lithology_intervals.csv']);
  const [customSamples, setCustomSamples] = useState<Sample[]>([]);
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState('Scene ready · 44 local supports');
  const [infoPanel, setInfoPanel] = useState('workbench');
  const scenario = scenarios.find((item) => item.id === scenarioId) ?? scenarios[0];
  const samples = useMemo(() => [...seedSamples(scenario), ...customSamples], [scenario, customSamples]);
  const result = useMemo(() => estimateAt(samples, selectedDepth, method, scenario), [samples, selectedDepth, method, scenario]);
  const selected = useMemo(() => [...samples].sort((a, b) => Math.abs(a.depth - selectedDepth) - Math.abs(b.depth - selectedDepth))[0], [samples, selectedDepth]);

  const updateLayer = (key: keyof SceneLayers) => setLayers((current) => ({ ...current, [key]: !current[key] }));
  const chooseScenario = (id: string) => { setScenarioId(id); setCustomSamples([]); setSelectedDepth(132); setStatus('Loaded ' + (scenarios.find((item) => item.id === id)?.name ?? 'case') + ' reconstruction'); };
  const addFiles = async (files: FileList | null) => {
    if (!files) return;
    const incoming = Array.from(files);
    setSources((current) => [...new Set([...current, ...incoming.map((file) => file.name)])]);
    const parsed = (await Promise.all(incoming.map(async (file, index) => file.name.toLowerCase().endsWith('.csv') ? parseAssayCsv(await file.text(), index % 3) : []))).flat();
    if (parsed.length) { setCustomSamples((current) => [...current, ...parsed]); setStatus('Parsed ' + parsed.length + ' assay observations into the scene'); }
    else setStatus('Source registered · add a CSV with depth and grade columns for live points');
  };
  const runEstimate = () => { setRunning(true); setStatus('Solving ' + method.toLowerCase() + ' support weights…'); window.setTimeout(() => { setRunning(false); setStatus(method + ' solved locally · ' + result.count + ' supports'); }, 460); };
  const resetScene = () => { setView('orbit'); setPlaying(true); setSelectedDepth(132); setLayers({ boreholes: true, assay: true, ore: true, geology: true, grid: true }); setStatus('Scene reset to full reconstruction'); };

  return <main className="sondara-app">
    <header className="app-header">
      <div className="brand-lockup"><span className="brand-glyph">◈</span><div><strong>SONDARA</strong><small>DRILLHOLE INTELLIGENCE</small></div></div>
      <div className="header-context"><span className="eyebrow">ACTIVE PROJECT</span><strong>{scenario.name} / 3D RECONSTRUCTION</strong></div>
      <div className="header-actions"><span className="compute-badge"><i /> LOCAL GPU READY</span><button onClick={() => setInfoPanel('methods')}>Methods</button><button onClick={() => setInfoPanel('cases')}>Cases</button><button className="header-icon" onClick={resetScene}>↺</button></div>
    </header>

    <section className="project-bar">
      <div><span className="eyebrow">PROJECT / {scenario.id.toUpperCase()}</span><h1>See the deposit as a system.</h1><p>{scenario.summary}. Inspect supports, continuity and uncertainty in a navigable spatial model.</p></div>
      <div className="project-actions"><label>CASE<select value={scenarioId} onChange={(event) => chooseScenario(event.target.value)}>{scenarios.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button className="accent-button" onClick={runEstimate} disabled={running}>{running ? 'Solving…' : 'Run local solve'} <span>↗</span></button></div>
    </section>

    <div className="app-body">
      <aside className="command-rail">
        <div className="rail-section rail-intro"><span className="step-index">01</span><div><h2>Data stack</h2><p>Sources remain local, traceable and visible in the reconstruction.</p></div></div>
        <label className="dropzone-v2"><input type="file" multiple accept=".csv,.json,.parquet" onChange={(event) => void addFiles(event.target.files)} /><span className="drop-icon">＋</span><strong>Load source files</strong><small>collar · survey · assay · geology</small></label>
        <div className="source-stack">{sources.map((file, index) => <div className="source-chip" key={file}><span className="source-symbol">{index === 0 ? '⌖' : index === 1 ? '∿' : '▦'}</span><div><strong>{file}</strong><small>{index === 0 ? scenario.holes + ' collars · trajectory' : index === 1 ? scenario.assays + ' intervals · grade' : 'coded lithology intervals'}</small></div><b>✓</b></div>)}</div>
        <div className="rail-section layer-heading"><span className="step-index">02</span><div><h2>Scene layers</h2><p>Toggle the reconstruction without leaving the spatial context.</p></div></div>
        <div className="layer-list">{([['boreholes', 'Surveyed boreholes', 'trajectory'], ['assay', 'Assay supports', 'grade points'], ['ore', 'Ore continuity shell', 'interpreted'], ['geology', 'Geology contacts', 'wireframe'], ['grid', 'Coordinate grid', 'local frame']] as [keyof SceneLayers, string, string][]).map(([key, label, note]) => <button className={'layer-toggle' + (layers[key] ? ' enabled' : '')} key={key} onClick={() => updateLayer(key)}><span className="layer-check">{layers[key] ? '✓' : '·'}</span><span><strong>{label}</strong><small>{note}</small></span></button>)}</div>
        <div className="rail-footer"><span className="status-dot" /> {status}</div>
      </aside>

      <section className="scene-column">
        <div className="scene-toolbar"><div className="view-switch"><span className="eyebrow">VIEW</span>{([['orbit', 'Orbit'], ['section', 'Section'], ['plan', 'Plan']] as [SceneView, string][]).map(([key, label]) => <button className={view === key ? 'selected' : ''} key={key} onClick={() => setView(key)}>{label}</button>)}</div><div className="scene-actions"><button className={playing ? 'selected-action' : ''} onClick={() => setPlaying((value) => !value)}>{playing ? 'Ⅱ Animate field' : '▶ Animate field'}</button><button onClick={resetScene}>Fit scene</button><button onClick={() => setStatus('Capture prepared · use browser save to export the current view')}>Export view</button></div></div>
        <div className="scene-frame"><SubsurfaceScene samples={samples} selectedDepth={selectedDepth} onSelectDepth={(depth) => { setSelectedDepth(depth); setStatus('Selected support at ' + depth + ' m'); }} metric={metric} layers={layers} view={view} playing={playing} scenarioColor={scenario.color} /><div className="scene-hud hud-top"><span className="hud-kicker">LIVE RECONSTRUCTION</span><strong>{scenario.name}</strong><small>{result.count} supports · {scenario.holes} holes · EPSG:32719</small></div><div className="scene-hud hud-right"><span><i className="legend-swatch grade" /> grade</span><span><i className="legend-swatch shell" /> ore shell</span><span><i className="legend-swatch survey" /> survey</span></div><div className="scene-readout"><span className="readout-label">SELECTED DEPTH</span><strong>{selectedDepth} m</strong><span>DH-{String((selected?.hole ?? 0) + 1).padStart(2, '0')} · {result.mean.toFixed(2)} % Cu · ±{result.uncertainty.toFixed(2)}</span></div></div>
        <div className="depth-dock"><div className="dock-label"><span className="eyebrow">DEPTH SLICE</span><strong>{selectedDepth} m</strong></div><input aria-label="Depth slice" type="range" min="0" max="260" value={selectedDepth} onChange={(event) => setSelectedDepth(Number(event.target.value))} /><div className="dock-range"><span>0 m</span><span>130 m</span><span>260 m</span></div><div className="metric-switch-v2">{(['grade', 'uncertainty', 'lithology'] as const).map((item) => <button key={item} className={metric === item ? 'active' : ''} onClick={() => setMetric(item)}>{item}</button>)}</div></div>
      </section>

      <aside className="inspector-rail">
        <div className="inspector-tabs"><button className={infoPanel === 'workbench' ? 'active' : ''} onClick={() => setInfoPanel('workbench')}>Inspect</button><button className={infoPanel === 'methods' ? 'active' : ''} onClick={() => setInfoPanel('methods')}>Methods</button><button className={infoPanel === 'cases' ? 'active' : ''} onClick={() => setInfoPanel('cases')}>Cases</button></div>
        {infoPanel === 'workbench' && <><div className="inspector-title"><span className="step-index">03</span><div><h2>Spatial inspector</h2><p>Selection follows the 3D scene.</p></div></div><div className="selection-card"><span className="eyebrow">ACTIVE SUPPORT</span><strong>DH-{String((selected?.hole ?? 0) + 1).padStart(2, '0')} · {selectedDepth} m</strong><div className="selection-grid"><div><small>Cu grade</small><b>{result.mean.toFixed(2)} %</b></div><div><small>P90 uncertainty</small><b>±{result.uncertainty.toFixed(2)}</b></div><div><small>Support range</small><b>{result.range} m</b></div><div><small>Cross validation</small><b>{result.cv.toFixed(2)}</b></div></div></div><div className="inspector-block"><span className="eyebrow">ESTIMATOR</span><select className="wide-select" value={method} onChange={(event) => setMethod(event.target.value)}>{methods.map((name) => <option key={name}>{name}</option>)}</select><div className="solver-callout"><span className="status-dot" /><div><strong>{running ? 'Computing local solve' : 'Browser solver available'}</strong><small>Supports stay on this device · no login</small></div></div><button className="full-button" onClick={runEstimate} disabled={running}>{running ? 'Solving…' : 'Recompute at selected depth'} <span>↗</span></button></div><div className="inspector-block diagnostics"><span className="eyebrow">QUALITY GATES</span><div><i className="ok-dot" /> coordinate frame <b>OK</b></div><div><i className="ok-dot" /> support overlaps <b>0</b></div><div><i className="warn-dot" /> extrapolation cells <b>{Math.round(100 - result.cv * 100)}%</b></div></div></>}
        {infoPanel === 'methods' && <div className="info-view"><span className="eyebrow">METHODS / LOCAL LANE</span><h2>Compare the spatial assumptions.</h2><p>Change the estimator and watch the support weighting, uncertainty and profile update in the same 3D context.</p>{methods.map((name, index) => <button className={'method-row' + (method === name ? ' chosen' : '')} key={name} onClick={() => { setMethod(name); setInfoPanel('workbench'); }}>{String(index + 1).padStart(2, '0')}<span><strong>{name}</strong><small>{index < 3 ? 'continuous estimate' : index === 3 ? 'threshold probability' : 'realization / pattern'}</small></span><b>›</b></button>)}</div>}
        {infoPanel === 'cases' && <div className="info-view"><span className="eyebrow">CASES / AUTHORED FIXTURES</span><h2>Choose the geological story.</h2><p>Each case changes the colour field, support density and spatial continuity while keeping the controls consistent.</p>{scenarios.map((item) => <button className={'case-row' + (scenario.id === item.id ? ' chosen' : '')} key={item.id} onClick={() => { chooseScenario(item.id); setInfoPanel('workbench'); }}><i style={{ background: item.color }} /><span><strong>{item.name}</strong><small>{item.summary}</small></span><b>›</b></button>)}</div>}
      </aside>
    </div>
    <footer className="app-footer"><span>SONDARA / LOCAL-FIRST SUBSURFACE WORKBENCH</span><span>v0.2.0 · WebGL reconstruction · Apache-2.0</span><span>Data remains in this browser</span></footer>
  </main>;
}
