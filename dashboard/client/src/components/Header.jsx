import React from 'react';
import { Building2, Radio } from 'lucide-react';

function Header({ organizations, selectedOrgId, onChangeOrg, isLoading }) {
  return (
    <header
      className="card"
      style={{
        padding: '18px 20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        position: 'sticky',
        top: 16,
        zIndex: 10,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 14,
            background: 'linear-gradient(135deg, #7f5af0, #82dbf7)',
            display: 'grid',
            placeItems: 'center',
            boxShadow: '0 10px 30px rgba(127, 90, 240, 0.35)',
          }}
        >
          <Building2 size={22} color="#0b1020" />
        </div>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: -0.02 + 'em' }}>Org Tables Dashboard</div>
          <div style={{ color: 'var(--text-secondary)', fontSize: 13 }}>FastAPI + React · salesmap_latest.db</div>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div className="pill">
          <span className="status-dot" />
          {isLoading ? 'Syncing data...' : `Organizations: ${organizations.length}`}
        </div>
        <select
          value={selectedOrgId || ''}
          onChange={(e) => onChangeOrg(e.target.value)}
          style={{
            padding: '10px 14px',
            minWidth: 260,
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid var(--card-border)',
            color: 'var(--text-primary)',
            borderRadius: 12,
            fontWeight: 600,
            outline: 'none',
          }}
        >
          <option value="" disabled>
            Select organization...
          </option>
          {organizations.map((org) => (
            <option key={org.id} value={org.id}>
              {org.name || org.id} {org.size ? `· ${org.size}` : ''}
            </option>
          ))}
        </select>
        <div className="pill" style={{ gap: 6 }}>
          <Radio size={14} />
          API ready
        </div>
      </div>
    </header>
  );
}

export default Header;
