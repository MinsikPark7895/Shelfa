import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import '../styles/BookDetail.css'
import '../styles/AdminPage.css'
import ReservationModal from './ReservationModal'
import { apiFetch } from '../api'

interface BookData {
  id: string; title: string; author: string; translator?: string; publisher: string
  shelf_location: string; cover_image_url: string; status: string; description?: string
}

function BookDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [book, setBook] = useState<BookData | null>(null)
  const [displayStatus, setDisplayStatus] = useState('available')
  const [isFavorite, setIsFavorite] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [showGearMenu, setShowGearMenu] = useState(false)
  const [showDevNotice, setShowDevNotice] = useState(false)
  const isAdmin = JSON.parse(localStorage.getItem('user') || '{}').role === 'admin'

  useEffect(() => { fetchBook() }, [id])

  const fetchBook = async () => {
    try {
      setLoadError(false)
      const [bookRes, loanRes, resRes] = await Promise.all([
        apiFetch(`/books/${id}`),
        apiFetch('/loans/me?limit=50'),
        apiFetch('/reservations/me?limit=50'),
      ])
      if (!bookRes.ok) { setLoadError(true); return }
      const book = await bookRes.json()
      setBook(book)
      setIsFavorite(book.is_favorited || false)

      const loanData = loanRes.ok ? await loanRes.json() : { items: [] }
      const resData = resRes.ok ? await resRes.json() : { items: [] }
      const myLoanIds = new Set(loanData.items?.map((l: any) => l.book.id) || [])
      const myResIds = new Set(resData.items?.filter((r: any) => r.status === 'PENDING').map((r: any) => r.book.id) || [])

      if (myLoanIds.has(id)) setDisplayStatus('my_loan')
      else if (myResIds.has(id)) setDisplayStatus('my_reservation')
      else if (book.status === 'AVAILABLE') setDisplayStatus('available')
      else setDisplayStatus('borrowed')
    } catch { setLoadError(true) }
  }

  const handleFavoriteToggle = async () => {
    if (isProcessing) return
    setIsProcessing(true)
    try {
      if (isFavorite) {
        await apiFetch(`/favorites/${id}`, { method: 'DELETE' })
        setIsFavorite(false)
      } else {
        await apiFetch(`/favorites/${id}`, { method: 'POST' })
        setIsFavorite(true)
      }
    } catch { alert('오류가 발생했습니다.') } finally { setIsProcessing(false) }
  }

  if (loadError) return (
    <div className="page-container">
      <div className="top-nav"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg><span className="logo-text">XYZ 도서관</span></div>
      <div style={{ textAlign: 'center', marginTop: '40%' }}>
        <p style={{ color: '#888', marginBottom: '12px' }}>도서 정보를 불러올 수 없습니다.</p>
        <button className="refresh-btn" style={{ fontSize: '14px' }} onClick={fetchBook}>↺ 새로고침</button>
      </div>
    </div>
  )

  if (!book) return <div className="page-container"><div className="top-nav"><span className="logo-text">로딩중...</span></div></div>

  const statusConfig: Record<string, any> = {
    available: { label: '대출가능', badgeClass: 'badge-available', buttonText: '예약하기', buttonDisabled: false },
    borrowed: { label: '대출불가', badgeClass: 'badge-unavailable', buttonText: '예약불가', buttonDisabled: true },
    my_loan: { label: '대출중', badgeClass: 'badge-myloan', buttonText: '이미 대출한 책입니다', buttonDisabled: true },
    my_reservation: { label: '예약완료', badgeClass: 'badge-myreserve', buttonText: '이미 예약한 책입니다', buttonDisabled: true },
  }
  const sc = statusConfig[displayStatus] || statusConfig.available

  return (
    <div className="page-container">
      <div className="top-nav"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg><span className="logo-text">XYZ 도서관</span></div>
      <div className="bookdetail-content">
        <div className="bookdetail-header" onClick={() => setShowGearMenu(false)}><h1 className="bookdetail-title">도서상세</h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {isAdmin && (
              <div className="admin-gear-wrap">
                <button className="bookdetail-favorite-btn" style={{ WebkitTapHighlightColor: 'transparent' }} onClick={(e) => { e.stopPropagation(); setShowGearMenu(v => !v) }}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="var(--navy)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="3" />
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                  </svg>
                </button>
                {showGearMenu && (
                  <div className="admin-gear-dropdown" onClick={(e) => e.stopPropagation()}>
                    <button className="admin-gear-item" onClick={() => { setShowGearMenu(false); setShowDevNotice(true) }}>도서 정보 수정</button>
                    <button className="admin-gear-item admin-gear-item--danger" onClick={() => { setShowGearMenu(false); setShowDevNotice(true) }}>도서 삭제</button>
                  </div>
                )}
              </div>
            )}
            <button className="bookdetail-favorite-btn" style={{ WebkitTapHighlightColor: 'transparent' }} onClick={(e) => { e.stopPropagation(); handleFavoriteToggle() }}>
              <svg viewBox="0 0 24 24" fill={isFavorite ? 'var(--navy)' : 'none'} stroke="var(--navy)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" /></svg>
            </button>
          </div>
        </div>
        <div className="bookdetail-cover-section">
          <div className="bookdetail-cover">
            {book.cover_image_url
              ? <img src={book.cover_image_url} alt={book.title} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              : <div className="bookdetail-cover-placeholder"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg></div>
            }
          </div>
        </div>
        <div className="bookdetail-badge-row"><span className={`bookdetail-badge ${sc.badgeClass}`}>{sc.label}</span></div>
        <div className="bookdetail-info">
          <h2 className="bookdetail-book-title">{book.title}</h2>
          <p className="bookdetail-meta">{book.author} 저자</p>
          <p className="bookdetail-publisher">{book.publisher}</p>
          <p className="bookdetail-class-number">{book.shelf_location}</p>
        </div>
        <div className="bookdetail-action">
          <button className={`bookdetail-reserve-btn ${sc.buttonDisabled ? 'disabled' : ''}`} onClick={() => !sc.buttonDisabled && setShowModal(true)} disabled={sc.buttonDisabled}>{sc.buttonText}</button>
        </div>
        {book.description && (
          <div className="bookdetail-synopsis"><h3 className="bookdetail-synopsis-title">줄거리</h3><p className="bookdetail-synopsis-text">{book.description}</p></div>
        )}
      </div>
      {showDevNotice && (
        <div className="modal-overlay" onClick={() => setShowDevNotice(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close-btn" onClick={() => setShowDevNotice(false)}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
            </button>
            <div className="modal-result">
              <div className="modal-result-icon"><svg viewBox="0 0 24 24" fill="none" stroke="#aaa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></svg></div>
              <p className="modal-result-text">추후 개발 예정입니다.</p>
              <button className="modal-btn-outline" onClick={() => setShowDevNotice(false)}>확인</button>
            </div>
          </div>
        </div>
      )}
      {showModal && (
        <ReservationModal
          bookId={String(id)}
          title={book.title}
          author={book.author}
          classNumber={book.shelf_location || ''}
          badgeLabel={sc.label}
          badgeClass={sc.badgeClass}
          onClose={() => setShowModal(false)}
          onSuccess={() => setDisplayStatus('my_reservation')}
        />
      )}
      <div className="tab-bar">
        <a className="tab-item" onClick={() => navigate('/home')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg><span className="tab-label">홈</span></a>
        <a className="tab-item" onClick={() => navigate('/my-library')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg><span className="tab-label">내 서재</span></a>
        <a className="tab-item" onClick={() => navigate('/mypage')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg><span className="tab-label">사용자</span></a>
        <a className="tab-item active" onClick={() => navigate('/search')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg><span className="tab-label">검색</span></a>
        <a className="tab-item" onClick={() => navigate('/notifications')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg><span className="tab-label">알림</span></a>
      </div>
    </div>
  )
}
export default BookDetail
