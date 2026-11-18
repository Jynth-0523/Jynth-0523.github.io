export function SiteHeader() {
  return (
    <header className="site-header">
      <a className="wordmark wordmark-text" href="/" aria-label="Factor Discovery home">
        <span><strong>Factor Discovery</strong><small>Automatic Factor Research</small></span>
      </a>
      <nav aria-label="Primary navigation">
        <a href="/#overview">Platform</a>
        <a href="/#example-data">Example data</a>
        <a href="/#process">Method</a>
        <a href="/#validation">Evidence</a>
        <a href="/#registry">Registry</a>
        <a href="/#reproducibility">Reproducibility</a>
      </nav>
      <a className="header-action" href="/discover">Start discovery</a>
    </header>
  );
}
