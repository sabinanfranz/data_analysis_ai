import React from 'react';

function Loader({ label }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div className="loader" />
      {label && <div className="muted">{label}</div>}
    </div>
  );
}

export default Loader;
