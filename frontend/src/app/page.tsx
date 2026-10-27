"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  Eye,
  FileSearch,
  GitBranch,
  Github,
  Lock,
  Search,
  ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api, type HealthResponse, type Repository } from "@/lib/api";
import { PrismIcon } from "@/components/icons";
import PrismDiagram from "@/components/PrismDiagram";
import styles from "./page.module.css";

export default function LandingPage() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [repos, setRepos] = useState<Repository[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);

  useEffect(() => {
    api.listRepos().then(r => setRepos(r.repositories)).catch(() => {});
    api.health().then(setHealth).catch(() => {});
  }, []);

  const handleConnect = async () => {
    if (!url.trim()) {
      setError("Please enter a repository URL");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const repo = await api.connectRepo(url.trim());
      router.push(`/repos/${repo.id}/onboarding`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to connect repository");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.ambient} aria-hidden="true" />
      <div className={styles.content}>
        <section className={styles.hero} aria-labelledby="home-heading">
          <div className={styles.heroCopy}>
            <div className={styles.identity}>
              <PrismIcon className={styles.brandIcon} aria-hidden="true" />
              <span>PRISM</span>
              <span className={styles.identityDivider} />
              <span className={styles.identityDescriptor}>REPOSITORY INTELLIGENCE</span>
            </div>
            <p className={styles.kicker}>
              <span className={styles.kickerMark} />
              SEE BEYOND THE DIFF
            </p>
            <h1 id="home-heading" className={styles.headline}>
              Understand
              <br />
              the <span>change.</span>
            </h1>
            <p className={styles.intro}>
              Explain the risk. Prove the review.
            </p>
            <p className={styles.description}>
              Persistent Repository Intelligence &amp; Security Mapping. Connect a
              repository for evidence-backed, plain-English security explanations
              for every code change.
            </p>
            <a className={styles.scrollCue} href="#connect">
              <span>GET STARTED</span>
              <ArrowDownRight aria-hidden="true" />
            </a>
          </div>

          <div className={styles.visual} aria-hidden="true">
            <PrismDiagram />
          </div>
        </section>

        <section className={styles.connectSection} id="connect" aria-labelledby="connect-heading">
          <div className={styles.connectHeading}>
            <span className={styles.sectionIndex}>01 / CONNECT</span>
            <h2 id="connect-heading">Start with a repository.</h2>
          </div>
          <div className={styles.connectForm}>
            <label className={styles.inputLabel} htmlFor="repository-url">
              Repository URL
            </label>
            <div className={styles.inputRow}>
              <Input
                id="repository-url"
                type="text"
                placeholder="https://github.com/owner/repo"
                value={url}
                onChange={e => setUrl(e.target.value)}
                onKeyDown={e => e.key === "Enter" && handleConnect()}
                className={styles.repositoryInput}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? "connect-error" : "connect-assurances"}
              />
              <Button
                onClick={handleConnect}
                disabled={loading}
                size="lg"
                className={styles.connectButton}
              >
                {loading ? "Connecting..." : "Connect repository"}
                {!loading && <ArrowRight className="ml-2 h-4 w-4" aria-hidden="true" />}
              </Button>
            </div>
            {error && (
              <p className={styles.error} id="connect-error" role="alert">
                {error}
              </p>
            )}
            <div className={styles.assurances} id="connect-assurances">
              <span>
                <Lock aria-hidden="true" />
                Source code stays on your infrastructure
              </span>
              <span>
                <ShieldCheck aria-hidden="true" />
                Evidence-backed analysis, never AI-only claims
              </span>
            </div>
          </div>
        </section>

        <section className={styles.statusSection} aria-label="System status">
          <div className={styles.statusHeading}>
            <span className={styles.sectionIndex}>LIVE STATUS</span>
            <span className={styles.statusPulse} />
          </div>
          <div className={styles.statusGrid}>
            <StatusItem
              icon={<Activity aria-hidden="true" />}
              label="LLM MODEL"
              value={health?.llm_available ? health.llm_model : "Not connected"}
              status={health?.llm_available ? "online" : "offline"}
            />
            <StatusItem
              icon={<ShieldCheck aria-hidden="true" />}
              label="BACKEND"
              value={health ? `v${health.version}` : "Checking..."}
              status={health ? "online" : "offline"}
            />
            <StatusItem
              icon={<GitBranch aria-hidden="true" />}
              label="DATABASE"
              value={health?.database || "Unknown"}
              status={health ? "online" : "offline"}
            />
          </div>
        </section>

        {repos.length > 0 && (
          <section className={styles.recentSection} aria-labelledby="recent-heading">
            <div className={styles.sectionTitleRow}>
              <div>
                <span className={styles.sectionIndex}>02 / YOUR WORKSPACE</span>
                <h2 id="recent-heading">Recently connected</h2>
              </div>
              <span className={styles.repoCount}>
                {String(repos.length).padStart(2, "0")} REPOSITORIES
              </span>
            </div>
            <div className={styles.repoList}>
              {repos.map(repo => (
                <button
                  key={repo.id}
                  onClick={() => router.push(`/repos/${repo.id}`)}
                  className={styles.repoButton}
                >
                  <span className={styles.repoIcon}>
                    <Github aria-hidden="true" />
                  </span>
                  <span className={styles.repoInfo}>
                    <span className={styles.repoName}>{repo.full_name}</span>
                    <span className={styles.repoMeta}>
                      {repo.provider} <span>·</span> {repo.default_branch}
                    </span>
                  </span>
                  <ArrowRight className={styles.repoArrow} aria-hidden="true" />
                </button>
              ))}
            </div>
          </section>
        )}

        <section className={styles.features} aria-labelledby="approach-heading">
          <div className={styles.featureIntro}>
            <span className={styles.sectionIndex}>03 / THE APPROACH</span>
            <h2 id="approach-heading">Clarity you can trace.</h2>
          </div>
          <FeatureItem
            number="A"
            icon={<FileSearch aria-hidden="true" />}
            title="Persistent intelligence"
            description="Index a repository once. Reuse unchanged entries. Maintain a version-aware understanding of the codebase."
          />
          <FeatureItem
            number="B"
            icon={<Search aria-hidden="true" />}
            title="Evidence-first review"
            description="Every claim links to source code, scanner results, or tool evidence. No AI-only safety claims."
          />
          <FeatureItem
            number="C"
            icon={<Eye aria-hidden="true" />}
            title="Plain-English reports"
            description="An executive summary for non-technical reviewers and technical evidence for engineers."
          />
        </section>

        <footer className={styles.footer}>
          <div className={styles.footerBrand}>
            <PrismIcon aria-hidden="true" />
            <span>PRISM</span>
          </div>
          <span>UNDERSTAND THE CHANGE. EXPLAIN THE RISK. PROVE THE REVIEW.</span>
        </footer>
      </div>
    </div>
  );
}

function StatusItem({
  icon,
  label,
  value,
  status,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  status: "online" | "offline";
}) {
  return (
    <div className={styles.statusItem}>
      <div className={styles.statusLabel}>
        {icon}
        <span>{label}</span>
        <span className={`${styles.statusDot} ${status === "online" ? styles.online : ""}`} />
      </div>
      <p>{value}</p>
    </div>
  );
}

function FeatureItem({
  number,
  icon,
  title,
  description,
}: {
  number: string;
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <article className={styles.featureItem}>
      <div className={styles.featureTopline}>
        <span>{number}</span>
        {icon}
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
    </article>
  );
}
