import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/Notifications.css'

interface Notification {
  id: number
  type: 'reserve' | 'return' | 'wishlist'
  message: string
  bookTitle: string
  bookMeta: string
  date: string
}

function Notifications() {
  const navigate = useNavigate()

  // DB 연동 예정 - 틀만
  const [notifications, setNotifications] = useState<Notification[]>([
    {
      id: 1,
      type: 'reserve',
      message: '예약하신 도서가 준비되었습니다.',
      bookTitle: '-',
      bookMeta: '저자 / 옮긴이 / 출판사 / 도서번호',
      date: '2026.06.10',
    },
    {
      id: 2,
      type: 'return',
      message: '대출 도서의 반납일이 다가왔습니다.',
      bookTitle: '-',
      bookMeta: '저자 / 옮긴이 / 출판사 / 도서번호',
      date: '2026.06.09',
    },
    {
      id: 3,
      type: 'wishlist',
      message: '관심도서가 대출 가능 상태입니다.',
      bookTitle: '-',
      bookMeta: '저자 / 옮긴이 / 출판사 / 도서번호',
      date: '2026.06.08',
    },
  ])

  const handleBookClick = (type: string) => {
    switch (type) {
      case 'reserve':
        navigate('/my-library?tab=storage')
        break
      case 'return':
        navigate('/my-library?tab=loans')
        break
      case 'wishlist':
        navigate('/my-library?tab=favorites')
        break
    }
  }

  const handleDelete = (id: number) => {
    setNotifications(prev => prev.filter(n => n.id !== id))
  }

  const handleClearAll = () => {
    setNotifications([])
  }

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

      <div className="noti-content">
        <div className="noti-header">
          <h1 className="noti-title">알림</h1>
          {notifications.length > 0 && (
            <button className="noti-clear-btn" onClick={handleClearAll}>전체 지우기</button>
          )}
        </div>

        {notifications.length === 0 ? (
          <div className="noti-empty">알림이 없습니다.</div>
        ) : (
          <div className="noti-list">
            {notifications.map(noti => (
              <div className="noti-item" key={noti.id}>
                <div className="noti-item-top">
                  <div className="noti-item-icon">
                    {noti.type === 'reserve' && (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" />
                      </svg>
                    )}
                    {noti.type === 'return' && (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
                      </svg>
                    )}
                    {noti.type === 'wishlist' && (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21.3l7.8-7.8 1-1.1a5.5 5.5 0 0 0 0-7.8z" />
                      </svg>
                    )}
                  </div>
                  <span className="noti-item-message">{noti.message}</span>
                  <button className="noti-item-delete" onClick={() => handleDelete(noti.id)}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="3 6 5 6 21 6" /><path d="M19 6l-1 14H6L5 6" /><path d="M10 11v6" /><path d="M14 11v6" /><path d="M9 6V4h6v2" />
                    </svg>
                  </button>
                </div>
                <div className="noti-item-date">{noti.date}</div>
                <div className="noti-book-card" onClick={() => handleBookClick(noti.type)}>
                  <div className="noti-book-cover"></div>
                  <div className="noti-book-info">
                    <div className="noti-book-title">{noti.bookTitle}</div>
                    <div className="noti-book-meta">{noti.bookMeta}</div>
                  </div>
                </div>
              </div>
            ))}
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
        <a className="tab-item" onClick={() => navigate('/my-library')}>
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
        <a className="tab-item active" onClick={() => navigate('/notifications')}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" />
          </svg>
          <span className="tab-label">알림</span>
        </a>
      </div>
    </div>
  )
}

export default Notifications