import type { Metadata } from "next";
import { SiteHeader } from "../site-header";
import { UploadDiscoveryWorkspace } from "../upload-discovery-workspace";

export const metadata: Metadata = {
  title: "Run Discovery — Factor Discovery",
  description: "Upload your own panel and run frequency-aware factor discovery in your browser.",
};

export default function DiscoverPage() {
  return (
    <main>
      <SiteHeader />
      <div className="site-shell discover-route">
        <UploadDiscoveryWorkspace />
        <footer className="simple-footer">
          <div className="footer-brand"><span><strong>Factor Discovery</strong><small>Automatic Factor Research</small></span></div>
          <p><a href="/">Platform overview</a> · <a href="/#reproducibility">Methods and source</a></p>
          <span>Research use only</span>
        </footer>
      </div>
    </main>
  );
}
