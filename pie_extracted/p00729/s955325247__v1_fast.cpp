#include <bits/stdc++.h>



using namespace std;



#define dprint(Exp,...) if(Exp){fprintf(stderr, __VA_ARGS__);}

#define printe(...) fprintf(stderr, __VA_ARGS__);

#define PrtExp(_Exp)  cerr<< #_Exp <<" = "<< (_Exp)

#define PrtExpN(_Exp)  cerr<< #_Exp <<" = "<< (_Exp) <<"\n"



#define SINT(n) scanf("%d",&n);

#define SINT2(n,m) scanf("%d %d",&n,&m);

#define SINT3(n,m,o) scanf("%d %d %d",&n,&m,&o);

#define SINT4(n,m,o,p) scanf("%d %d %d %d",&n,&m,&o,&p);

#define SINT5(n,m,o,p,q) scanf("%d %d %d %d %d",&n,&m,&o,&p,&q);



#define SLL(n) scanf("%lld",&n);

#define SLL2(n,m) scanf("%lld %lld",&n,&m);

#define SLL3(n,m,o) scanf("%lld %lld %lld",&n,&m,&o);





#define PINT(n) printf("%d",(int)(n));

#define PINT2(n,m) printf("%d %d",(int)(n),(int)(m));

#define PINT3(n,m,l) printf("%d %d %d",(int)(n),(int)(m),(int)(l));

#define PLL(n) printf("%lld",(long long)(n));



#define PINTN(n) printf("%d\n",(int)(n));

#define PINT2N(n,m) printf("%d %d\n",(int)(n),(int)(m));

#define PINT3N(n,m,l) printf("%d %d %d\n",(int)(n),(int)(m),(int)(l));

#define PLLN(n) printf("%lld\n",(long long)(n));





#define rep(i,a) for(int i=0;i<a;i++)

#define reP(i,a) for(int i=0;i<=a;i++)

#define Rep(i,a) for(int i=a-1;i>=0;i--)

#define ReP(i,a) for(int i=a;i>=0;i--)



#define rEp(i,a) for(i=0;i<a;i++)

#define rEP(i,a) for(i=0;i<=a;i++)

#define REp(i,a) for(i=a-1;i>=0;i--)

#define REP(i,a) for(i=a;i>=0;i--)



#define repft(i,a,b) for(int i=a;i<b;i++)

#define repfT(i,a,b) for(int i=a;i<=b;i++)

#define Repft(i,a,b) for(int i=a-1;i>=b;i--)

#define RepfT(i,a,b) for(int i=a;i>=b;i--)



#define FILL(a,v) fill(begin(a),end(a), v)

#define FILL0(a) memset(a,0,sizeof(a))

#define FILL1(a) memset(a,-1,sizeof(a))



typedef long long ll;

typedef unsigned long long ull;

typedef pair<int, int> Pi;

typedef pair<ll, ll>   Pll;



typedef pair<Pi, int> Piii;



#define fs first

#define sc second



const int INF = 0x1f1f1f1f; //522,133,279

const ll INFLL = 0x1f1f1f1f1f1f1f1fLL; //2,242,545,357,980,376,863





int T[10000][1300];







int main() {

	

	int N, M;



	for (;;) {

		SINT2(N, M);

		if (N + M == 0)break;

		int r;

		SINT(r);



		FILL0(T);



		rep(i, r) {

			int t, n, m, s;

			SINT4(t, n, m, s);

			if (s == 1) {

				T[m][t]++;

			} else {

				T[m][t]--;

			}

		}



		rep(i, M+1) {

			rep(j, 1280) {

				T[i][j + 1] += T[i][j];

				// printf("%4d: %d\n",j, T[i][j]);

			}

		}

		SINT(r);

		rep(i, r) {

			int s, e, m;

			SINT3(s, e, m);

			int ret = 0;



			repft(j, s, e) {

				if (T[m][j] > 0) ret++;

			}

			PINTN(ret);

		}

	}





}