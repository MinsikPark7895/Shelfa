import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/MyPage.css'

function MyPage() {
  const navigate = useNavigate()
  const [showModal, setShowModal] = useState(false)
  const [borrowedCount, setBorrowedCount] = useState(0)

  const user = JSON.parse(localStorage.getItem('user') || '{}')

  useEffect(() => {
    if (user.id) fetchBorrowCount()
  }, [])

  const fetchBorrowCount = async () => {
    try {
      const res = await fetch(`http://localhost:3001/reservations?userId=${user.id}&status=loaned`)
      const loans = await res.json()
      setBorrowedCount(loans.length)
    } catch { /* */ }
  }

  const handleLogout = () => {
    localStorage.removeItem('user')
    navigate('/login')
  }

  return (
    <div className="page-container">
      <div className="top-nav">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
          <path d="M8 7h6" /><path d="M8 11h4" />
        </svg>
        <span className="logo-text">XYZ 도서관</span>
      </div>

      <div className="mypage-content">
        <div className="mypage-profile">
          <div className="mypage-profile-img">
            <svg viewBox="0 0 60 60" fill="none">
              <circle cx="30" cy="30" r="30" fill="#c8d8c8" />
              <circle cx="30" cy="22" r="10" fill="#7a9a7a" />
              <ellipse cx="30" cy="46" rx="16" ry="12" fill="#7a9a7a" />
            </svg>
          </div>
          <div className="mypage-profile-info">
            <div className="mypage-name-row">
              <span className="mypage-user-name">{user.name || '-'} 님</span>
              <button className="mypage-edit-btn" onClick={() => navigate('/profile-edit')}>
                <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M13.5 2.5l2 2L5 15H3v-2L13.5 2.5z" /></svg>
              </button>
            </div>
            <div className="mypage-membership">
              <span className="mypage-membership-label">MEMBERSHIP NO.</span>
              <span className="mypage-membership-no">{user.membershipNo || '-'}</span>
            </div>
          </div>
        </div>

        <div className="mypage-qr-section">
          <div className="mypage-qr-box">
            <img src={new URL('../assets/qr-placeholder.png', import.meta.url).href} alt="QR코드" className="mypage-qr-img" />
          </div>
          <p className="mypage-qr-title">스캔하여 출입 및 도서 대출</p>
          <p className="mypage-qr-sub">무인 대출기 및 게이트에서 사용 가능합니다.</p>
        </div>

        <div className="mypage-status-section">
          <div className="mypage-status-header">
            <span className="mypage-status-title">대출 현황</span>
            <span className="mypage-status-detail" onClick={() => navigate('/my-library?tab=loans')}>더보기 &gt;</span>
          </div>
          <div className="mypage-status-card">
            <div className="mypage-borrow-row">
              <svg className="mypage-borrow-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M4 19.5A2.5 2.5 0 016.5 17H20" /><path d="M4 19.5V5a2 2 0 012-2h14v14H6.5A2.5 2.5 0 004 19.5z" />
              </svg>
              <span className="mypage-borrow-label">대출 중</span>
              <div className="mypage-borrow-count">
                <span className="mypage-borrow-num">{borrowedCount}</span>
                <span className="mypage-borrow-max"> / {user.maxBorrow || 5}권</span>
              </div>
            </div>
          </div>
        </div>

        <button className="mypage-logout-btn" onClick={handleLogout}>로그아웃</button>
      </div>

      {showModal && (
        <div className="mypage-modal-overlay" onClick={() => setShowModal(false)}>
          <div className="mypage-modal" onClick={(e) => e.stopPropagation()}>
            <p className="mypage-modal-text">현재 지원하지 않는 기능입니다.</p>
            <button className="mypage-modal-btn" onClick={() => setShowModal(false)}>확인</button>
          </div>
        </div>
      )}

      <div className="tab-bar">
        <a className="tab-item" onClick={() => navigate('/home')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg><span className="tab-label">홈</span></a>
        <a className="tab-item" onClick={() => navigate('/my-library')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg><span className="tab-label">내 서재</span></a>
        <a className="tab-item active" onClick={() => navigate('/mypage')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg><span className="tab-label">사용자</span></a>
        <a className="tab-item" onClick={() => navigate('/search')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg><span className="tab-label">검색</span></a>
        <a className="tab-item" onClick={() => navigate('/notifications')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg><span className="tab-label">알림</span></a>
      </div>
    </div>
  )
}

export default MyPage
