import type { ReactNode } from "react";

export interface PageHeadingProps {
  title: ReactNode;
  description?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}

export default function PageHeading({ title, description, eyebrow, actions, children }: PageHeadingProps) {
  return (
    <div className="page-heading">
      <div className="page-heading-main">
        <div className="min-w-0">
          {eyebrow && <p className="page-eyebrow">{eyebrow}</p>}
          <h1 className="page-title">{title}</h1>
          {description && <div className="page-description ui-copy">{description}</div>}
        </div>
        {actions && <div className="page-heading-actions">{actions}</div>}
      </div>
      {children && <div className="page-heading-context">{children}</div>}
    </div>
  );
}
