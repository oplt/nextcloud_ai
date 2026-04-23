export function SkeletonLine({ width = '100%' }: { width?: string }) {
  return <span className="skeleton skeleton--line" style={{ width }} aria-hidden="true" />;
}

export function StatCardSkeleton() {
  return (
    <article className="card stat-card stat-card--skeleton" aria-busy="true" aria-label="Loading statistic">
      <span className="stat-card__label skeleton skeleton--line skeleton--short" />
      <strong className="stat-card__value skeleton skeleton--line skeleton--medium" />
    </article>
  );
}

export function HeroCardSkeleton() {
  return (
    <article className="card hero-card hero-card--skeleton" aria-busy="true" aria-label="Loading profile">
      <span className="eyebrow skeleton skeleton--line skeleton--tiny" />
      <h2 className="skeleton skeleton--line skeleton--wide" />
      <p className="skeleton skeleton--line" />
    </article>
  );
}
