import React from 'react';

function PeopleTable({ people = [], selectedId, onSelect }) {
  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontWeight: 700 }}>People</div>
        <div className="pill-badge">{people.length} rows</div>
      </div>
      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th style={{ width: 120 }}>Role</th>
              <th style={{ width: 70, textAlign: 'center' }}>Deals</th>
            </tr>
          </thead>
          <tbody>
            {people.length === 0 && (
              <tr>
                <td colSpan={3} className="empty-hint">
                  No people in this organization
                </td>
              </tr>
            )}
            {people.map((person) => (
              <tr
                key={person.id}
                className={selectedId === person.id ? 'selected' : ''}
                onClick={() => onSelect && onSelect(person.id)}
              >
                <td style={{ fontWeight: 600 }}>{person.name || person.id}</td>
                <td style={{ color: 'var(--text-secondary)' }}>{person.title || '—'}</td>
                <td style={{ textAlign: 'center' }}>
                  <span className="pill-badge">{person.dealCount ?? 0}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default PeopleTable;
