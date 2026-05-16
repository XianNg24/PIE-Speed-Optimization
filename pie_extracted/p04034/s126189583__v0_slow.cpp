#include <bits/stdc++.h>

using namespace std;



#define REP(i,n) for(int i=0;i<n;i++)

#define rep(i,n) for(int i=0;i<n;i++)

#define INF 1<<29

#define LINF LLONG_MAX/3

#define MP make_pair

#define PB push_back

#define EB emplace_back

#define ALL(v) (v).begin(),(v).end()

#define debug(x) cerr<<#x<<":"<<x<<endl

#define debug2(x,y) cerr<<#x<<","<<#y":"<<x<<","<<y<<endl

#define CININIT cin.tie(0),ios::sync_with_stdio(false)

template<typename T> ostream& operator<<(ostream& os,const vector<T>& vec){ os << "["; for(const auto& v : vec){ os << v << ","; } os << "]"; return os; }



typedef long long ll;

typedef unsigned long long ull;

typedef pair<int,int> pii;

typedef vector<int> vi;

typedef vector<vi> vvi;



int N,M;



int main(){

    cin>>N>>M;

    vi num(N,1);

    vector<bool> ok(N,false);

    ok[0]=true;

    rep(i,M){

        int x,y;cin>>x>>y;

        x--,y--;

        if(ok[x]){

            if(num[x]>1){

                ok[y]=true;

            }else{

                ok[y]=true;

                ok[x]=false;

            }

        }

        num[y]++;

        num[x]--;

    }

    int ans=0;

    rep(i,N) if(ok[i]) ans++;

    cout << ans << endl;

}
