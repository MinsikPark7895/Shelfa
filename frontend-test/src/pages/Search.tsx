import { useState, useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import '../styles/Search.css'

const STORAGE_KEY = 'shelfa-recent-searches'
interface RecentSearch { keyword: string; category: string }
interface BookResult { id: string; title: string; author: string; publisher: string; classNumber: string; coverImage: string; status: string; category: string; availableCount: number; displayStatus: string }

const PLACEHOLDER_MAP: Record<string, string> = {
  '전체': '제목, 저자, 키워드 검색', '저자': '저자명을 입력하세요', '출판사': '출판사명을 입력하세요', '분류': '분류명을 입력하세요',
}

function Search() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const searchInputRef = useRef<HTMLInputElement>(null)
  const [searchValue, setSearchValue] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [isFocused, setIsFocused] = useState(false)
  const [recentSearches, setRecentSearches] = useState<RecentSearch[]>([])
  const [searchCategory, setSearchCategory] = useState('전체')
  const [showDropdown, setShowDropdown] = useState(false)
  const [lastSearchCategory, setLastSearchCategory] = useState('전체')
  const [searchResults, setSearchResults] = useState<BookResult[]>([])
  const [isProcessing, setIsProcessing] = useState(false)
  const [favoriteBookIds, setFavoriteBookIds] = useState<Set<string>>(new Set())

  const user = JSON.parse(localStorage.getItem('user') || '{}')

  useEffect(() => {
    fetchFavorites()
    let saved: string | null = null
    try {
      saved = localStorage.getItem(STORAGE_KEY)
      if (saved) {
        const parsed = JSON.parse(saved)
        if (Array.isArray(parsed) && parsed.length > 0) {
          if (typeof parsed[0] === 'string') setRecentSearches(parsed.map((s: string) => ({ keyword: s, category: '전체' })))
          else setRecentSearches(parsed)
        }
      }
    } catch { localStorage.removeItem(STORAGE_KEY) }
    const q = searchParams.get('q')
    const cat = searchParams.get('cat')
    if (cat) { setSearchCategory(cat); setLastSearchCategory(cat) }
    if (q) {
      setSearchValue(q); setIsSearching(true)
      fetchBooks(q, cat || '전체')
      try {
        const current = saved ? JSON.parse(saved) : []
        const normalized: RecentSearch[] = Array.isArray(current) && current.length > 0 && typeof current[0] === 'string'
          ? current.map((s: string) => ({ keyword: s, category: '전체' })) : current
        const updated = [{ keyword: q, category: cat || '전체' }, ...normalized.filter((s: RecentSearch) => !(s.keyword === q && s.category === (cat || '전체')))].slice(0, 10)
        saveSearches(updated)
      } catch { saveSearches([{ keyword: q, category: cat || '전체' }]) }
    }
  }, [searchParams])

  const fetchFavorites = async () => {
    if (!user.id) return
    try {
      const res = await fetch(`http://localhost:3001/favorites?userId=${user.id}`)
      const favs = await res.json()
      setFavoriteBookIds(new Set(favs.map((f: any) => String(f.bookId))))
    } catch { /* */ }
  }

  const fetchBooks = async (keyword: string, category: string) => {
    try {
      const [booksRes, resRes] = await Promise.all([
        fetch('http://localhost:3001/books'),
        fetch('http://localhost:3001/reservations')
      ])
      const allBooks = await booksRes.json()
      const allReservations = await resRes.json()

      // 각 bookId별 예약+대출 건수 카운팅
      const borrowCount: Record<string, number> = {}
      const myReservedIds = new Map<string, string>()
      allReservations.forEach((r: any) => {
        if (r.status === 'reserved' || r.status === 'loaned') {
          const bid = String(r.bookId)
          borrowCount[bid] = (borrowCount[bid] || 0) + 1
          if (user.id && r.userId === user.id) {
            if (r.status === 'reserved') myReservedIds.set(bid, 'my_reservation')
            else if (r.status === 'loaned') myReservedIds.set(bid, 'my_loan')
          }
        }
      })

      const kw = keyword.toLowerCase()
      const filtered = allBooks.filter((book: any) => {
        if (category === '전체') return book.title.toLowerCase().includes(kw) || book.author.toLowerCase().includes(kw) || book.publisher.toLowerCase().includes(kw) || book.category.toLowerCase().includes(kw)
        if (category === '저자') return book.author.toLowerCase().includes(kw)
        if (category === '출판사') return book.publisher.toLowerCase().includes(kw)
        if (category === '분류') return book.category.toLowerCase().includes(kw)
        return false
      }).map((book: any) => {
        const bid = String(book.id)
        let displayStatus = 'available'
        if (myReservedIds.has(bid)) displayStatus = myReservedIds.get(bid)!
        else if ((borrowCount[bid] || 0) >= book.availableCount) displayStatus = 'borrowed'
        return { ...book, displayStatus }
      })
      setSearchResults(filtered)
    } catch { setSearchResults([]) }
  }

  const saveSearches = (searches: RecentSearch[]) => { setRecentSearches(searches); localStorage.setItem(STORAGE_KEY, JSON.stringify(searches)) }
  const handleSearch = () => {
    const trimmed = searchValue.trim()
    if (!trimmed) return
    const updated = [{ keyword: trimmed, category: searchCategory }, ...recentSearches.filter(s => !(s.keyword === trimmed && s.category === searchCategory))].slice(0, 10)
    saveSearches(updated); setIsSearching(true); setLastSearchCategory(searchCategory); setIsFocused(false); setShowDropdown(false)
    searchInputRef.current?.blur(); fetchBooks(trimmed, searchCategory)
  }
  const handleDeleteOne = (item: RecentSearch) => { saveSearches(recentSearches.filter(s => !(s.keyword === item.keyword && s.category === item.category))) }
  const handleDeleteAll = () => { saveSearches([]) }
  const handleRecentClick = (item: RecentSearch) => {
    setSearchValue(item.keyword); setSearchCategory(item.category); setLastSearchCategory(item.category)
    saveSearches([item, ...recentSearches.filter(s => !(s.keyword === item.keyword && s.category === item.category))])
    setIsSearching(true); setIsFocused(false); fetchBooks(item.keyword, item.category)
  }

  const handleToggleFavorite = async (bookId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!user.id) { alert('로그인이 필요합니다.'); return }
    if (isProcessing) return
    setIsProcessing(true)
    try {
      const res = await fetch(`http://localhost:3001/favorites?userId=${user.id}`)
      const allFavs = await res.json()
      const targetFavs = allFavs.filter((f: any) => String(f.bookId) === String(bookId))

      if (targetFavs.length > 0) {
        for (const fav of targetFavs) {
          await fetch(`http://localhost:3001/favorites/${fav.id}`, { method: 'DELETE' })
        }
      } else {
        await fetch('http://localhost:3001/favorites', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ userId: user.id, bookId: String(bookId) })
        })
      }
      fetchFavorites()
    } catch { /* */ } finally { setIsProcessing(false) }
  }

  const getCategoryLabel = (cat: string) => {
    const map: Record<string, string> = { '전체': '전체', '저자': '작가', '출판사': '출판사', '분류': '분류' }
    return map[cat] || cat
  }

  return (
    <div className="page-container">
      <div className="top-nav">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg>
        <span className="logo-text">XYZ 도서관</span>
      </div>
      <div className="search-content">
        <div className="search-input-section">
          <div className="search-input-bar">
            <div className="search-bar-dropdown" onClick={() => setShowDropdown(!showDropdown)}>
              <span className="search-bar-dropdown-text">{searchCategory}</span>
              <span className="search-bar-dropdown-arrow">▼</span>
              {showDropdown && (<div className="search-bar-dropdown-menu">
                {['전체', '저자', '출판사', '분류'].map(cat => (
                  <div key={cat} className={`search-bar-dropdown-item${searchCategory === cat ? ' active' : ''}`}
                    onClick={(e) => { e.stopPropagation(); setSearchCategory(cat); setShowDropdown(false) }}>{cat}</div>
                ))}
              </div>)}
            </div>
            <input ref={searchInputRef} className="search-input-field" type="text"
              placeholder={PLACEHOLDER_MAP[searchCategory] || '검색어를 입력하세요'} value={searchValue}
              onChange={(e) => setSearchValue(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') handleSearch() }}
              onFocus={() => { setIsFocused(true); setIsSearching(false) }} />
            <svg className="search-bar-icon-btn" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" onClick={handleSearch}>
              <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </div>
        </div>
        {isSearching ? (
          <div className="search-result-section">
            <div className="search-result-summary">
              '<span className="search-result-highlight">{lastSearchCategory} : {searchValue}</span>'에 대한 검색결과 총 <span className="search-result-highlight">{searchResults.length}</span>건
            </div>
            {searchResults.length === 0 ? <div className="search-result-empty">검색 결과가 없습니다.</div> : (
              <div className="search-result-list">{searchResults.map(book => (
                <div className="search-result-card" key={book.id} onClick={() => navigate(`/book/${book.id}`)}>
                  <div className="search-result-cover"><div className="search-result-cover-placeholder"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /><path d="M8 7h6" /><path d="M8 11h4" /></svg></div></div>
                  <div className="search-result-info">
                    <div className="search-result-title-row">
                      <div className="search-result-title">{book.title}</div>
                      <button className="search-result-fav-btn" onClick={(e) => handleToggleFavorite(String(book.id), e)}>
                        <svg viewBox="0 0 24 24" fill={favoriteBookIds.has(String(book.id)) ? '#E03131' : 'none'} stroke={favoriteBookIds.has(String(book.id)) ? '#E03131' : 'var(--gray-400)'} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" />
                        </svg>
                      </button>
                    </div>
                    <div className="search-result-meta">{book.classNumber}</div>
                    <div className="search-result-meta">{book.author} 지음</div>
                    <div className="search-result-meta">{book.publisher}</div>
                    <div className="search-result-bottom">
                      {book.displayStatus === 'available' && (<><span className="badge-available">대출가능</span><button className="search-result-reserve-btn" onClick={(e) => { e.stopPropagation(); navigate(`/book/${book.id}`) }}>예약하기</button></>)}
                      {(book.displayStatus === 'borrowed' || book.displayStatus === 'my_loan') && (<><span className="badge-unavailable">대출불가</span><button className="search-result-reserve-btn disabled" disabled onClick={(e) => e.stopPropagation()}>예약불가</button></>)}
                      {book.displayStatus === 'my_reservation' && (<><span className="badge-myreserve">예약완료</span><button className="search-result-reserve-btn disabled" disabled onClick={(e) => e.stopPropagation()}>예약완료</button></>)}
                    </div>
                  </div>
                </div>
              ))}</div>
            )}
          </div>
        ) : isFocused && (
          <div className="search-recent">
            <div className="search-recent-header">
              <span className="search-recent-title">최근 검색어</span>
              {recentSearches.length > 0 && <button className="search-recent-clear" onClick={handleDeleteAll}>전체삭제</button>}
            </div>
            {recentSearches.length === 0 ? <div className="search-recent-empty">최근 검색어가 없습니다.</div> : (
              <div className="search-recent-tags">{recentSearches.map((item, idx) => (
                <div className="search-recent-tag" key={`${item.category}-${item.keyword}-${idx}`}>
                  <span onClick={() => handleRecentClick(item)}>{getCategoryLabel(item.category)} : {item.keyword}</span>
                  <button className="search-recent-tag-delete" onClick={() => handleDeleteOne(item)}>×</button>
                </div>
              ))}</div>
            )}
          </div>
        )}
      </div>
      <div className="tab-bar">
        <a className="tab-item" onClick={() => navigate('/home')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg><span className="tab-label">홈</span></a>
        <a className="tab-item" onClick={() => navigate('/my-library')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg><span className="tab-label">내서재</span></a>
        <a className="tab-item" onClick={() => navigate('/mypage')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg><span className="tab-label">사용자</span></a>
        <a className="tab-item active" onClick={() => navigate('/search')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg><span className="tab-label">검색</span></a>
        <a className="tab-item" onClick={() => navigate('/notifications')}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg><span className="tab-label">알림</span></a>
      </div>
    </div>
  )
}
export default Search
