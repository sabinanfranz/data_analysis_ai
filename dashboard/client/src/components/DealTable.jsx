import React from 'react';

const formatAmount = (val) => {
  if (val === null || val === undefined || val === '') return '—';
  const num = Number(val);
  if (Number.isNaN(num)) return '—';
  return `${(num / 1e8).toFixed(2)}억`;
};

const formatDate = (dateStr) => {
  if (!dateStr) return '—';
  return String(dateStr).split(' ')[0];
};

function DealTable({ deals = [], selectedDealId, onSelectDeal, hasPerson }) {
  const emptyCopy = hasPerson ? 'No deals for this person' : 'Select a person to view deals';

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontWeight: 700 }}>Deals</div>
        <div className="pill-badge">{deals.length} rows</div>
      </div>
      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th>Deal</th>
              <th style={{ width: 90, textAlign: 'right' }}>금액</th>
              <th style={{ width: 110, textAlign: 'center' }}>마감/예정</th>
            </tr>
          </thead>
          <tbody>
            {(!hasPerson || deals.length === 0) && (
              <tr>
                <td colSpan={3} className="empty-hint">
                  {emptyCopy}
                </td>
              </tr>
            )}
            {hasPerson &&
              deals.map((deal) => (
                <tr
                  key={deal.id}
                  className={selectedDealId === deal.id ? 'selected' : ''}
                  onClick={() => onSelectDeal && onSelectDeal(deal.id)}
                >
                  <td style={{ fontWeight: 600 }}>{deal.name || deal.id}</td>
                  <td style={{ textAlign: 'right', color: 'var(--text-secondary)' }}>{formatAmount(deal.amount)}</td>
                  <td style={{ textAlign: 'center' }}>
                    {formatDate(deal.deadline || deal.expected_date || deal.expectedDate)}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default DealTable;
