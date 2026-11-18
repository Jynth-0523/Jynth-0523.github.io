"use client";

function buildSampleCsv() {
  const lines = ["asset_id,date,available_date,forward_return,value,quality,momentum,volatility"];
  for (let month = 0; month < 72; month += 1) {
    const date = new Date(Date.UTC(2020 + Math.floor(month / 12), month % 12, 1)).toISOString().slice(0, 10);
    for (let asset = 1; asset <= 20; asset += 1) {
      const value = ((asset * 7 + month * 3) % 23) / 22;
      const quality = ((asset * 11 + month * 5) % 29) / 28;
      const momentum = Math.sin((asset + month) / 3);
      const volatility = 0.1 + ((asset * 5 + month * 2) % 17) / 40;
      const noise = Math.sin(asset * 13 + month * 7) * 0.006;
      const forwardReturn = 0.035 * value + 0.025 * quality + 0.018 * momentum - 0.025 * volatility + noise;
      lines.push([`A${String(asset).padStart(2, "0")}`, date, date, forwardReturn.toFixed(6), value.toFixed(6), quality.toFixed(6), momentum.toFixed(6), volatility.toFixed(6)].join(","));
    }
  }
  return `${lines.join("\n")}\n`;
}

export function SampleDataPanel() {
  function downloadSample() {
    const blob = new Blob([buildSampleCsv()], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "factor-discovery-example.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="section example-data-section" id="example-data">
      <div className="section-intro">
        <div><span className="section-index">01 / EXAMPLE DATA</span><h2>See the format before using the platform.</h2></div>
        <p>This synthetic panel is documentation only. It is separate from the discovery workspace and from the recorded research results below.</p>
      </div>
      <div className="example-data-card">
        <div>
          <span>SYNTHETIC MONTHLY PANEL</span>
          <h3>1,440 rows · 20 assets · 72 periods · 4 candidate features</h3>
          <p>The file demonstrates the required entity, date, point-in-time availability, forward-return target, and numeric-feature columns. It contains no licensed or registry data.</p>
        </div>
        <div className="example-schema" aria-label="Example columns">
          {[
            ["asset_id", "Entity identifier"],
            ["date", "Signal date"],
            ["available_date", "Feature availability"],
            ["forward_return", "Prediction target"],
            ["value … volatility", "Candidate features"],
          ].map(([column, meaning]) => <div key={column}><code>{column}</code><span>{meaning}</span></div>)}
        </div>
        <button type="button" onClick={downloadSample}>Download example CSV <span>↓</span></button>
      </div>
    </section>
  );
}
