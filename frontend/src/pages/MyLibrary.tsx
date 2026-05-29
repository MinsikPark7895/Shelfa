import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import '../styles/MyLibrary.css'

function MyLibrary() {
  const [searchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') || 'loans')
  const navigate = useNavigate()

  // DB 연동 예정 - 틀만
  const loanBooks: any[] = []
  const favoriteBooks: any[] = []
  const storageBooks: any[] = []

  // 보관 중 상태인 책만 (수령완료 제외)
  const activeStorageCount = storageBooks.filter(b => b.status === 'storing').length

  return (
    <div className="page-container">
      {/* Top Nav */}
      <div className="top-nav">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
          <path d="M8 7h6" /><path d="M8 11h4" />
        </svg>
        <span className="logo-text">XYZ 도서관</span>
      </div>

      <div className="mylibrary-content">
        <h1 className="mylibrary-title">내 서재</h1>

        {/* 탭 */}
        <div className="tab-group">
          <button className={`tab-btn ${activeTab === 'loans' ? 'active' : ''}`} onClick={() => setActiveTab('loans')}>대출현황</button>
          <button className={`tab-btn ${activeTab === 'favorites' ? 'active' : ''}`} onClick={() => setActiveTab('favorites')}>관심도서</button>
          <button className={`tab-btn ${activeTab === 'storage' ? 'active' : ''}`} onClick={() => setActiveTab('storage')}>보관도서</button>
        </div>

        {/* 대출현황 탭 */}
        {activeTab === 'loans' && (
          <div className="tab-content">
            <div className="section-count">
              <span className="section-count-title">총 {loanBooks.length}권의 대출도서</span>
            </div>
            {loanBooks.length === 0 ? (
              <div className="tab-content-empty">대출한 책이 없습니다.</div>
            ) : (
              <div className="book-list">
                {/* TODO: DB 연동 후 책 카드 목록 */}
              </div>
            )}
          </div>
        )}

        {/* 관심도서 탭 */}
        {activeTab === 'favorites' && (
          <div className="tab-content">
            <div className="section-count">
              <span className="section-count-title">총 {favoriteBooks.length}권의 관심도서</span>
            </div>
            {favoriteBooks.length === 0 ? (
              <div className="tab-content-empty">관심도서가 없습니다.</div>
            ) : (
              <div className="book-list">
                {/* TODO: DB 연동 후 책 카드 목록 */}
              </div>
            )}
          </div>
        )}

        {/* 보관도서 탭 */}
        {activeTab === 'storage' && (
          <div className="tab-content">
            <div className="section-count">
              <span className="section-count-title">보관 중인 도서</span>
              <span className="section-count-number">현재 {activeStorageCount}권 보관중</span>
            </div>
            {activeStorageCount > 0 && (
              <div className="info-banner">
                <div className="info-banner-icon">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="16" x2="12" y2="12" />
                    <line x1="12" y1="8" x2="12.01" y2="8" />
                  </svg>
                </div>
                <span className="info-banner-text">수령 기한이 지나면 도서가 자동으로 반납됩니다.</span>
              </div>
            )}
            {storageBooks.length === 0 ? (
              <div className="tab-content-empty">보관 중인 도서가 없습니다.</div>
            ) : (
              <div className="book-list">
                {/* TODO: DB 연동 후 보관 카드 목록 */}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Bottom Tab Bar */}
      <div className="tab-bar">
        <a className="tab-item" onClick={() => navigate('/home')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" />
          </svg>
          <span className="tab-label">홈</span>
        </a>
        <a className="tab-item active" onClick={() => navigate('/my-library')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
          </svg>
          <span className="tab-label">내 서재</span>
        </a>
        <a className="tab-item" onClick={() => navigate('/mypage')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
          </svg>
          <span className="tab-label">사용자</span>
        </a>
        <a className="tab-item" onClick={() => navigate('/search')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <span className="tab-label">검색</span>
        </a>
        <a className="tab-item" onClick={() => navigate('/notifications')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" />
          </svg>
          <span className="tab-label">알림</span>
        </a>
      </div>
    </div>
  )
}

export default MyLibrary
