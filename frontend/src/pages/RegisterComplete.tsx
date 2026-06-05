import { useNavigate } from 'react-router-dom'

function RegisterComplete() {
  const navigate = useNavigate()

  return (
    <div className="page-container">
      <div className="top-nav">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
          <path d="M8 7h6" /><path d="M8 11h4" />
        </svg>
        <span className="logo-text">XYZ 도서관</span>
      </div>

      <div className="register-content">
        <p className="register-complete-label">회원가입 완료창</p>
        <div className="register-card register-complete-card">
          <div className="register-complete-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="#4CAF50" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <polyline points="9 12 11.5 14.5 16 9.5" />
            </svg>
          </div>
          <p className="register-complete-text">가입이 완료되었습니다.</p>
          <hr className="register-complete-divider" />
          <button className="register-complete-btn" onClick={() => navigate('/login')}>로그인</button>
        </div>
      </div>
    </div>
  )
}

export default RegisterComplete
