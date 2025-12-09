import React from 'react';

function MemoList({ title, items, emptyText }) {
  return (
    <div className="memo-card">
      <div className="memo-title">{title}</div>
      {items && items.length > 0 ? (
        items.map((memo, idx) => (
          <div key={memo.id || idx} className="memo-item">
            <div style={{ fontWeight: 600 }}>{memo.text || '메모 내용 없음'}</div>
            <small>{memo.createdAt ? new Date(memo.createdAt).toLocaleDateString() : '날짜 없음'}</small>
          </div>
        ))
      ) : (
        <div className="empty-hint">{emptyText}</div>
      )}
    </div>
  );
}

function MemoStack({ personMemos = [], dealMemos = [] }) {
  return (
    <div className="memo-stack">
      <MemoList title="People memo" items={personMemos} emptyText="Select a person to see memos" />
      <MemoList title="Deal memo" items={dealMemos} emptyText="Select a deal to see memos" />
    </div>
  );
}

export default MemoStack;
