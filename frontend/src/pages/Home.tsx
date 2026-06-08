import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/Home.css'
import ReservationModal from './ReservationModal'
import { apiFetch } from '../api'

const PLACEHOLDER_MAP: Record<string, string> = {
  '전체': '제목, 저자, 키워드 검색',
  '저자': '저자명을 입력하세요',
  '출판사': '출판사명을 입력하세요',
  '분류': '분류명을 입력하세요',
}

interface BookData {
  id: string
  title: string
  author: string
  cover_image_url: string
  shelf_location: string
  status: string
  isAvailable: boolean
  displayStatus: string
}

function Home() {
  const [currentSlide, setCurrentSlide] = useState(0)
  const navigate = useNavigate()
  const searchInputRef = useRef<HTMLInputElement>(null)
  const [searchCategory, setSearchCategory] = useState('전체')
  const [showDropdown, setShowDropdown] = useState(false)

  const [loanCount, setLoanCount] = useState(0)
  const [nearestDday, setNearestDday] = useState('-')
  const [nearestDueDate, setNearestDueDate] = useState('-')
  const [reservationCount, setReservationCount] = useState(0)
  const [wishBooks, setWishBooks] = useState<BookData[]>([])
  const [selectedBook, setSelectedBook] = useState<BookData | null>(null)
  const [summaryError, setSummaryError] = useState(false)
  const [wishlistError, setWishlistError] = useState(false)

  useEffect(() => {
    const timer = setInterval(() => { setCurrentSlide(prev => (prev + 1) % 2) }, 5000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    fetchLibrarySummary()
    fetchWishlist()
  }, [])

  const fetchLibrarySummary = async () => {
    try {
      setSummaryError(false)
      const res = await apiFetch('/users/me/summary')
      if (res.ok) {
        const data = await res.json()
        setLoanCount(data.active_loans ?? 0)
        setReservationCount(data.active_reservations ?? 0)
        if (data.nearest_due_date) {
          const d = new Date(data.nearest_due_date)
          const diffDays = Math.ceil((d.getTime() - Date.now()) / 86400000)
          setNearestDday(`D-${Math.max(0, diffDays)}`)
          setNearestDueDate(`${d.getMonth() + 1}/${d.getDate()}`)
        }
      } else {
        setSummaryError(true)
      }
    } catch { setSummaryError(true) }
  }

  const fetchWishlist = async () => {
    try {
      setWishlistError(false)
      const [favRes, loanRes, resRes] = await Promise.all([
        apiFetch('/favorites/me?limit=5'),
        apiFetch('/loans/me?limit=50'),
        apiFetch('/reservations/me?limit=50'),
      ])
      if (!favRes.ok) { setWishlistError(true); return }
      const favData = await favRes.json()
      const loanData = loanRes.ok ? await loanRes.json() : { items: [] }
      const resData = resRes.ok ? await resRes.json() : { items: [] }

      const myLoanIds = new Set(loanData.items?.map((l: any) => l.book.id) || [])
      const myResIds = new Set(resData.items?.filter((r: any) => r.status === 'PENDING').map((r: any) => r.book.id) || [])

      const books: BookData[] = (favData.items || []).map((f: any) => {
        let displayStatus = 'available'
        if (myLoanIds.has(f.book.id)) displayStatus = 'my_loan'
        else if (myResIds.has(f.book.id)) displayStatus = 'my_reservation'
        else if (f.book.status !== 'AVAILABLE') displayStatus = 'borrowed'
        return { ...f.book, isAvailable: displayStatus === 'available', displayStatus }
      })
      setWishBooks(books)
    } catch { setWishlistError(true) }
  }

  const handleSearchSubmit = () => {
    const val = searchInputRef.current?.value.trim()
    if (val) navigate(`/search?q=${val}&cat=${searchCategory}`)
  }

  return (
    <div className="page-container">
      <div className="top-nav">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" />
          <path d="M8 7h6" /><path d="M8 11h4" />
        </svg>
        <span className="logo-text">XYZ 도서관</span>
        {JSON.parse(localStorage.getItem('user') || '{}').role === 'admin' && (
          <button className="admin-nav-btn" onClick={() => navigate('/admin')}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
            </svg>
          </button>
        )}
      </div>

      <div className="home-content">
        <div className="search-bar-section">
          <div className="search-bar">
            <div className="search-bar-dropdown" onClick={() => setShowDropdown(!showDropdown)}>
              <span className="search-bar-dropdown-text">{searchCategory}</span>
              <span className="search-bar-dropdown-arrow">▼</span>
              {showDropdown && (
                <div className="search-bar-dropdown-menu">
                  {['전체', '저자', '출판사', '분류'].map(cat => (
                    <div key={cat} className={`search-bar-dropdown-item${searchCategory === cat ? ' active' : ''}`}
                      onClick={(e) => { e.stopPropagation(); setSearchCategory(cat); setShowDropdown(false); }}>{cat}</div>
                  ))}
                </div>
              )}
            </div>
            <input ref={searchInputRef} className="search-bar-input" type="text"
              placeholder={PLACEHOLDER_MAP[searchCategory] || '검색어를 입력하세요'}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSearchSubmit() }} />
            <svg className="search-bar-icon-btn" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" onClick={handleSearchSubmit}>
              <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </div>
        </div>

        <div className="home-section">
          <div className="home-section-header">
            <span className="home-section-title">공지사항</span>
            <a className="home-section-more" onClick={() => navigate('/notices')}>전체보기</a>
          </div>
          <div className="notice-card" onClick={() => navigate('/notices/벌레잡기')}>
            <div className="notice-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /></svg></div>
            <div className="notice-content"><div className="notice-title">도서관 정기 방역 작업 안내 (6/15)</div><div className="notice-date">2026.06.07</div></div>
          </div>
          <div className="notice-card" onClick={() => navigate('/notices/신작소설')}>
            <div className="notice-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg></div>
            <div className="notice-content"><div className="notice-title">6월 신작 도서 목록 안내</div><div className="notice-date">2026.06.02</div></div>
          </div>
        </div>

        <div className="home-section">
          <div className="banner-slider">
            <div className="banner-track" style={{ transform: `translateX(-${currentSlide * 50}%)` }}>
              <div className="banner-slide banner-slide-1" onClick={() => navigate('/event/딩동댕정답')}>
                <span className="banner-tag">진행 중인 이벤트</span><div className="banner-title">XYZ 독서 골든벨 참가자 모집</div>
              </div>
              <div className="banner-slide banner-slide-2" onClick={() => navigate('/event/인간시대의끝이도래했다')}>
                <span className="banner-tag">AI 추천</span><div className="banner-title">AI가 추천하는 이달의 도서</div>
              </div>
            </div>
            <div className="banner-dots">
              <div className={`banner-dot ${currentSlide === 0 ? 'active' : ''}`} onClick={() => setCurrentSlide(0)}></div>
              <div className={`banner-dot ${currentSlide === 1 ? 'active' : ''}`} onClick={() => setCurrentSlide(1)}></div>
            </div>
          </div>
        </div>

        <div className="home-section">
          <div className="home-section-header">
            <span className="home-section-title">내 서재</span>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              {summaryError && <button className="refresh-btn" onClick={fetchLibrarySummary}>↺ 새로고침</button>}
              <a className="home-section-more" onClick={() => navigate('/my-library')}>더보기</a>
            </div>
          </div>
          <div className="library-card">
            <div className="library-card-label">대출 중인 도서</div>
            <div className="library-card-number-row">
              <span className="library-card-number">{loanCount}</span>
              <span className="library-card-unit">권</span>
            </div>
            <div className="library-card-divider"></div>
            <div className="library-card-book-row">
              <span className="library-card-book-title">반납일까지</span>
              <span className="library-card-dday">{nearestDday}</span>
            </div>
          </div>
          <div className="stat-row">
            <div className="stat-card">
              <div className="stat-label">반납 예정</div>
              <div className="stat-value">📅 {nearestDueDate}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">예약 도서</div>
              <div className="stat-value">📋 {reservationCount}건</div>
            </div>
          </div>
        </div>

        <div className="home-section">
          <div className="home-section-header">
            <span className="home-section-title">위시리스트</span>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              {wishlistError && <button className="refresh-btn" onClick={fetchWishlist}>↺ 새로고침</button>}
              <a className="home-section-more" onClick={() => navigate('/my-library?tab=favorites')}>더보기</a>
            </div>
          </div>
          {wishBooks.length === 0 ? (
            <div className="wish-empty">즐겨찾기한 도서가 없습니다.</div>
          ) : (
            <div className="wish-list">
              {wishBooks.map(book => (
                <div className="wish-card" key={book.id}>
                  <div className="wish-cover" onClick={() => navigate(`/book/${book.id}`)}>
                    {book.cover_image_url ? <img src={book.cover_image_url} alt={book.title} /> : (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg>
                    )}
                  </div>
                  <div className="wish-title">{book.title}</div>
                  <div className="wish-author">{book.author}</div>
                  {book.displayStatus === 'available' && (<><div className="wish-badge badge-available">대출가능</div><button className="wish-reserve-btn" onClick={() => setSelectedBook(book)}>예약하기</button></>)}
                  {book.displayStatus === 'borrowed' && (<><div className="wish-badge badge-unavailable">대출불가</div><button className="wish-reserve-btn disabled" disabled>예약불가</button></>)}
                  {book.displayStatus === 'my_loan' && (<><div className="wish-badge badge-unavailable">대출불가</div><button className="wish-reserve-btn disabled" disabled>예약불가</button></>)}
                  {book.displayStatus === 'my_reservation' && (<><div className="wish-badge badge-myreserve">예약완료</div><button className="wish-reserve-btn disabled" disabled>예약완료</button></>)}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {selectedBook && (
        <ReservationModal
          bookId={selectedBook.id}
          title={selectedBook.title}
          author={selectedBook.author}
          classNumber={selectedBook.shelf_location || ''}
          badgeLabel="대출가능"
          badgeClass="badge-available"
          onClose={() => setSelectedBook(null)}
          onSuccess={() => fetchWishlist()}
        />
      )}

      <div className="tab-bar">
        <a className="tab-item active" onClick={() => navigate('/home')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg><span className="tab-label">홈</span></a>
        <a className="tab-item" onClick={() => navigate('/my-library')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg><span className="tab-label">내 서재</span></a>
        <a className="tab-item" onClick={() => navigate('/mypage')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg><span className="tab-label">사용자</span></a>
        <a className="tab-item" onClick={() => navigate('/search')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg><span className="tab-label">검색</span></a>
        <a className="tab-item" onClick={() => navigate('/notifications')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg><span className="tab-label">알림</span></a>
      </div>
    </div>
  )
}

export default Home
