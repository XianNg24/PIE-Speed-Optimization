#ifdef LOCAL111

#else

	#define NDEBUG

#endif

#include <bits/stdc++.h>



using namespace std;



#define endl '\n'

#define ALL(a)  (a).begin(),(a).end()

#define SZ(a) int((a).size())

#define FOR(i,a,b) for(int i=(a);i<(b);++i)

#define RFOR(i,a,b) for (int i=(b)-1;i>=(a);i--)

#define REP(i,n)  FOR(i,0,n)

#define RREP(i,n) for (int i=(n)-1;i>=0;i--)

#define RBP(i,a) for(auto& i : a)

#ifdef LOCAL111

	#define DEBUG(x) cout<<#x<<": "<<(x)<<endl

#else

	#define DEBUG(x) true

#endif

#define F first

#define S second

#define SNP string::npos

#define WRC(hoge) cout << "Case #" << (hoge)+1 << ": "

#define INF 1e8

#define rangej(a,b,c) ((a) <= (c) and (c) < (b))

#define rrangej(b,c) rangej(0,b,c)

template<typename T> void pite(T a, T b){ for(T ite = a; ite != b; ite++) cout << (ite == a ? "" : " ") << *ite; cout << endl;}

template<typename T> bool chmax(T& a, T b){if(a < b){a = b; return true;} return false;}

template<typename T> bool chmin(T& a, T b){if(a > b){a = b; return true;} return false;}



typedef pair<int,int> P;

typedef long long int LL;

typedef unsigned long long ULL;

typedef pair<LL,LL> LP;



void ios_init(){

	//cout.setf(ios::fixed);

	//cout.precision(12);

#ifdef LOCAL111

	return;

#endif

	ios::sync_with_stdio(false); cin.tie(0);	

}



typedef vector<int> vi;



int main()

{

	ios_init();

	int n,m;

	while(cin >> n >> m and n != 0){

		int r;

		cin >> r;

		vector<vi> st(m,vi(1261,0));

		REP(i,r){

			bool s;

			int pn;

			int sm;

			int ti;

			cin >> ti >> pn >> sm >> s;

			ti--;

			sm--;

			if(s){

			//	DEBUG(ti);

				st[sm][ti]++;

			}else{

				st[sm][ti]--;

			}

		}

		REP(i,m) {

			FOR(j,1,SZ(st[i])){

				st[i][j] += st[i][j-1];

			//	cout << st[i][j];

			}

			//cout << endl;

		}

		//REP(i,m) pite(ALL(st[i]));

		int q;

		cin >> q;

		REP(i,q){

			int ts,te,ms;

			int ans = 0;

			cin >> ts >> te >> ms;

			ts--;

			te--;

			ms--;

			FOR(j,ts,te){

				ans += bool(st[ms][j]);

			}

			cout << ans << endl;

		}

	}

	return 0;

}