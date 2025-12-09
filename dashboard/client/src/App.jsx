import React, { useEffect, useMemo, useState } from 'react';
import Header from './components/Header';
import CompanySection from './components/CompanySection';
import PeopleSection from './components/PeopleSection';
import ErrorBanner from './components/ErrorBanner';
import Loader from './components/Loader';
import './components/Layout.css';

const API_BASE = import.meta.env.VITE_API_BASE || '';

function App() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedOrgId, setSelectedOrgId] = useState(null);
  const [withDealsSelection, setWithDealsSelection] = useState({ personId: null, dealId: null });
  const [withoutDealsSelection, setWithoutDealsSelection] = useState({ personId: null, dealId: null });

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch(`${API_BASE}/api/initial-data`);
      if (!res.ok) throw new Error('Failed to load data from API');
      const payload = await res.json();
      setData(payload);
      setSelectedOrgId(payload.organizations?.[0]?.id || null);
    } catch (err) {
      setError(err.message || 'Unable to load data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  useEffect(() => {
    setWithDealsSelection({ personId: null, dealId: null });
    setWithoutDealsSelection({ personId: null, dealId: null });
  }, [selectedOrgId]);

  const organizations = data?.organizations || [];
  const dealsByPersonId = data?.dealsByPersonId || {};
  const peopleMemosById = data?.peopleMemosById || {};
  const dealMemosById = data?.dealMemosById || {};

  const peopleWithDeals = useMemo(() => {
    if (!data || !selectedOrgId) return [];
    return (data.peopleWithDeals || []).filter((p) => p.organizationId === selectedOrgId);
  }, [data, selectedOrgId]);

  const peopleWithoutDeals = useMemo(() => {
    if (!data || !selectedOrgId) return [];
    return (data.peopleWithoutDeals || []).filter((p) => p.organizationId === selectedOrgId);
  }, [data, selectedOrgId]);

  const companyMemos = selectedOrgId && data ? data.companyMemos?.[selectedOrgId] || [] : [];

  if (loading) {
    return (
      <div className="page-shell" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Loader label="Loading dashboard..." />
      </div>
    );
  }

  if (error) {
    return (
      <div className="page-shell">
        <ErrorBanner message={error} onRetry={fetchData} />
      </div>
    );
  }

  const hasOrganizations = organizations.length > 0;

  return (
    <div className="page-shell">
      <Header
        organizations={organizations}
        selectedOrgId={selectedOrgId}
        onChangeOrg={setSelectedOrgId}
        isLoading={!data}
      />

      {hasOrganizations && selectedOrgId ? (
        <>
          <CompanySection memos={companyMemos} />

          <PeopleSection
            title="People (With Deals)"
            people={peopleWithDeals}
            dealsByPersonId={dealsByPersonId}
            peopleMemosById={peopleMemosById}
            dealMemosById={dealMemosById}
            selectedPersonId={withDealsSelection.personId}
            selectedDealId={withDealsSelection.dealId}
            onSelectPerson={(pid) => setWithDealsSelection({ personId: pid, dealId: null })}
            onSelectDeal={(did) => setWithDealsSelection((prev) => ({ ...prev, dealId: did }))}
            allowDealSelection
          />

          <PeopleSection
            title="People (Without Deals)"
            people={peopleWithoutDeals}
            dealsByPersonId={dealsByPersonId}
            peopleMemosById={peopleMemosById}
            dealMemosById={dealMemosById}
            selectedPersonId={withoutDealsSelection.personId}
            selectedDealId={withoutDealsSelection.dealId}
            onSelectPerson={(pid) => setWithoutDealsSelection({ personId: pid, dealId: null })}
            onSelectDeal={(did) => setWithoutDealsSelection((prev) => ({ ...prev, dealId: did }))}
          />
        </>
      ) : (
        <div className="card" style={{ padding: '32px', marginTop: '24px', textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 600, marginBottom: 8 }}>No organizations found</div>
          <div className="muted">Make sure the snapshot DB has organizations with people or deals.</div>
        </div>
      )}
    </div>
  );
}

export default App;
