import React, { useMemo } from 'react';
import PeopleTable from './PeopleTable';
import DealTable from './DealTable';
import MemoStack from './MemoStack';

function PeopleSection({
  title,
  people,
  dealsByPersonId,
  peopleMemosById,
  dealMemosById,
  selectedPersonId,
  selectedDealId,
  onSelectPerson,
  onSelectDeal,
  allowDealSelection = false,
}) {
  const currentDeals = useMemo(() => {
    if (!selectedPersonId) return [];
    return dealsByPersonId[selectedPersonId] || [];
  }, [dealsByPersonId, selectedPersonId]);

  const personMemos = selectedPersonId ? peopleMemosById[selectedPersonId] || [] : [];
  const dealMemos = selectedDealId ? dealMemosById[selectedDealId] || [] : [];

  return (
    <section className="section-shell">
      <div className="section-header">
        <div>
          <div className="section-title">{title}</div>
          <div className="section-subtitle">3-column people / deal / memo layout</div>
        </div>
        <div className="pill">{people.length} people</div>
      </div>

      <div className="people-grid">
        <div className="card-panel">
          <PeopleTable people={people} selectedId={selectedPersonId} onSelect={onSelectPerson} />
        </div>

        <div className="card-panel">
          <DealTable
            deals={currentDeals}
            selectedDealId={selectedDealId}
            onSelectDeal={allowDealSelection ? onSelectDeal : undefined}
            hasPerson={Boolean(selectedPersonId)}
          />
        </div>

        <div className="card-panel">
          <MemoStack personMemos={personMemos} dealMemos={dealMemos} />
        </div>
      </div>
    </section>
  );
}

export default PeopleSection;
