import type { Metadata } from "next";
import { FactorRegistryPanel } from "./factor-registry-panel";
import { release } from "./platform-data";
import { SampleDataPanel } from "./sample-data-panel";
import { SiteHeader } from "./site-header";

export const metadata: Metadata = {
  title: "Factor Discovery — Automatic Factor Research",
  description: "A browser-based platform for auditable factor discovery across daily, weekly, monthly, and quarterly panels.",
};

const process = [
  { step: "01", label: "Data contract", value: "Audit", note: "Check keys, frequency, completeness, point-in-time availability, and forward-return alignment." },
  { step: "02", label: "Candidate generation", value: "Generate", note: "Enumerate deterministic transformations and optional bounded AI proposals from selected feature names." },
  { step: "03", label: "Train screening", value: "Screen", note: "Measure cross-sectional signal strength and remove candidates that fail pre-specified hygiene rules." },
  { step: "04", label: "Redundancy control", value: "Prune", note: "Reduce correlated exposures before any combination is selected." },
  { step: "05", label: "Frozen selection", value: "Select", note: "Choose weights on a separate sample, then freeze the candidate before evaluation." },
  { step: "06", label: "Out-of-sample evidence", value: "Validate", note: "Apply purging, HAC inference, multiplicity control, trading costs, and full-year walk-forward blocks." },
] as const;

const protocol = [
  { label: "Candidate space", title: "Defined before validation", text: "The engine enumerates a finite candidate family. Outcome data do not steer expression generation." },
  { label: "Model selection", title: "Separated by role", text: "Train screens, Selection freezes the combination, and Calibration evaluates it without rewriting earlier decisions." },
  { label: "Evidence standard", title: "Costs and time matter", text: "A candidate must survive purging, multiple-testing control, transaction costs, and rolling out-of-sample evaluation." },
] as const;

export default function Home() {
  const calibrationPosition = Math.min(100, release.calibrationConfidence * 100);
  const thresholdPosition = release.calibrationThreshold * 100;

  return (
    <main>
      <SiteHeader />
      <div className="site-shell">
        <section className="hero" id="overview">
          <div className="hero-copy-block">
            <span className="release-kicker">BROWSER-BASED FACTOR RESEARCH</span>
            <h1>Discover factors. <em>Audit every step.</em></h1>
            <p>Bring a daily, weekly, monthly, or quarterly asset panel. The platform audits the data, generates candidates, separates research stages, and reports why each candidate passed or failed.</p>
            <div className="hero-actions">
              <a className="primary-action" href="/discover">Start with your data <span>→</span></a>
              <a className="text-action" href="#example-data">View the separate example dataset</a>
            </div>
          </div>
          <aside className="release-card" aria-label="Platform capabilities">
            <div className="release-card-head"><span className="status-dot" /><span>PUBLIC RESEARCH PLATFORM</span></div>
            <div className="release-result"><span>Supported observations</span><strong>4 frequencies</strong><p>Daily, weekly, monthly, and quarterly panels use frequency-specific horizons and validation windows.</p></div>
            <dl className="release-details">
              <div><dt>Execution</dt><dd>In browser</dd></div>
              <div><dt>Data upload</dt><dd>None</dd></div>
              <div><dt>Candidate features</dt><dd>Up to 50</dd></div>
              <div><dt>Result exports</dt><dd>JSON · CSV · MD</dd></div>
            </dl>
          </aside>
        </section>

        <section className="release-strip" aria-label="Platform capacity">
          <div><strong>4</strong><span>supported frequencies</span></div>
          <div><strong>500k</strong><span>rows per browser run</span></div>
          <div><strong>50</strong><span>selectable numeric features</span></div>
          <div><strong>500</strong><span>candidate budget</span></div>
          <div><strong>0</strong><span>rows sent to the server</span></div>
        </section>

        <SampleDataPanel />

        <section className="section process-section" id="process">
          <div className="section-intro">
            <div><span className="section-index">02 / RESEARCH METHOD</span><h2>From uploaded panel to auditable evidence.</h2></div>
            <p>The functional workspace is a separate page. The method below describes what happens after a user supplies data.</p>
          </div>
          <div className="process-grid">
            {process.map((item) => <article className="process-card" key={item.step}><span className="process-step">{item.step}</span><strong>{item.value}</strong><h3>{item.label}</h3><p>{item.note}</p></article>)}
          </div>
        </section>

        <section className="section validation-section" id="validation">
          <div className="section-intro light-intro">
            <div><span className="section-index">03 / RECORDED EVIDENCE</span><h2>A real development result—not a final model.</h2></div>
            <p>The registry below is copied from stored research artifacts. The complete outcome includes both the calibration result and the later cost-aware failure.</p>
          </div>
          <div className="validation-layout">
            <article className="confidence-panel">
              <div className="confidence-heading"><span>DEVELOPMENT CALIBRATION SCORE</span><b>{release.calibrationConfidence.toFixed(4)}</b></div>
              <div className="confidence-scale" aria-label={`Development calibration score ${release.calibrationConfidence.toFixed(4)}, soft threshold ${release.calibrationThreshold.toFixed(2)}`}>
                <span className="confidence-fill" style={{ width: `${calibrationPosition}%` }} />
                <i className="threshold-mark" style={{ left: `${thresholdPosition}%` }}><em>0.55 soft threshold</em></i>
              </div>
              <div className="scale-labels"><span>0.00</span><span>1.00</span></div>
              <p>This soft development gate passed. It did <strong>not</strong> establish a final investable factor or override the subsequent cost-aware evaluation.</p>
            </article>
            <div className="evidence-grid">
              <article><span>RECORDED</span><strong>Stored artifact result</strong><p>Component IDs, expressions, diagnostics, and weights are read from the frozen development output.</p></article>
              <article className="evidence-failed"><span>FAILED</span><strong>Cost-aware gate</strong><p>The later development check failed its net-spread requirements after trading costs.</p></article>
              <article><span>NO</span><strong>Final model created</strong><p>No production or final investment model was created from this result.</p></article>
              <article><span>UNTOUCHED</span><strong>Formal holdout</strong><p>Formal out-of-sample observations were not accessed for this recorded run.</p></article>
            </div>
          </div>
        </section>

        <FactorRegistryPanel />

        <section className="section protocol-section" id="protocol">
          <div className="section-intro">
            <div><span className="section-index">05 / RESEARCH PROTOCOL</span><h2>Rules that make a result interpretable.</h2></div>
            <p>Professional readers should be able to distinguish observed evidence from process claims, and exploratory results from genuinely untouched evaluation.</p>
          </div>
          <div className="protocol-grid">
            {protocol.map((item) => <article key={item.label}><span>{item.label}</span><h3>{item.title}</h3><p>{item.text}</p></article>)}
          </div>
          <div className="limitations">
            <div><span>LIMITATIONS &amp; USE</span><h3>Research evidence is not an investment claim.</h3></div>
            <ul>
              <li>The displayed registry is a historical development snapshot, not a list of validated tradable strategies.</li>
              <li>Component-level Train diagnostics do not establish standalone economic significance.</li>
              <li>Historical relationships may weaken, reverse, or disappear after costs and implementation constraints.</li>
              <li>The platform is informational and does not constitute investment advice or a recommendation to trade.</li>
            </ul>
          </div>
        </section>

        <section className="section reproducibility-section" id="reproducibility">
          <div className="section-intro">
            <div><span className="section-index">06 / REPRODUCIBILITY</span><h2>Inspect the method. Export the evidence.</h2></div>
            <p>The executable browser engine and methods note are directly downloadable, and every completed research run produces portable evidence files.</p>
          </div>
          <div className="reproducibility-grid">
            <a href="/factor-discovery.worker.js" download><span>ENGINE SOURCE</span><strong>Download the browser worker</strong><p>Readable JavaScript containing audit, candidate generation, inference, cost, and walk-forward logic.</p><b>DOWNLOAD ↓</b></a>
            <a href="/research-method.md" download><span>METHODS NOTE</span><strong>Download the research contract</strong><p>Input schema, frequency rules, validation stages, limits, and interpretation boundaries.</p><b>DOWNLOAD ↓</b></a>
            <article><span>RUN EXPORTS</span><strong>Evidence from your own panel</strong><p>Every completed run can export full JSON, factor definitions, walk-forward observations, and a readable validation report.</p><b>GENERATED IN DISCOVERY</b></article>
          </div>
        </section>

        <footer className="simple-footer">
          <div className="footer-brand"><span><strong>Factor Discovery</strong><small>Automatic Factor Research</small></span></div>
          <p>Auditable discovery · Explicit evidence boundaries · Downloadable method</p>
          <span>Research use only</span>
        </footer>
      </div>
    </main>
  );
}
