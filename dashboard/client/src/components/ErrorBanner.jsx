import React from 'react';
import { AlertTriangle, RefreshCcw } from 'lucide-react';

function ErrorBanner({ message, onRetry }) {
  return (
    <div
      className="card"
      style={{
        padding: '18px 20px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        borderColor: 'rgba(239, 68, 68, 0.3)',
        background: 'linear-gradient(120deg, rgba(239, 68, 68, 0.15), rgba(12, 16, 26, 0.8))',
      }}
    >
      <AlertTriangle color="#f87171" />
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 700, marginBottom: 4 }}>Failed to load data</div>
        <div className="muted">{message}</div>
      </div>
      {onRetry && (
        <button className="button secondary" onClick={onRetry} style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <RefreshCcw size={16} />
          Retry
        </button>
      )}
    </div>
  );
}

export default ErrorBanner;
