import React from 'react';
import { FileText } from 'lucide-react';

function CompanySection({ memos = [] }) {
  const hasMemos = memos.length > 0;

  return (
    <section className={`company-card ${hasMemos ? 'has-memos' : ''}`}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: hasMemos ? 12 : 4 }}>
        <div className="badge">
          <FileText size={14} />
          Company memos
        </div>
        <span className="muted">{memos.length} item(s)</span>
      </div>

      {hasMemos ? (
        <div className="company-memo-grid">
          {memos.map((memo, idx) => (
            <div key={memo.id || idx} className="memo-item">
              <div style={{ fontWeight: 600, marginBottom: 6 }}>{memo.text || '내용 없음'}</div>
              <small>{memo.createdAt ? new Date(memo.createdAt).toLocaleDateString() : '작성일 없음'}</small>
            </div>
          ))}
        </div>
      ) : (
        <div className="muted">이 회사에 등록된 메모가 없습니다. 상단 드롭다운에서 회사를 선택하세요.</div>
      )}
    </section>
  );
}

export default CompanySection;
