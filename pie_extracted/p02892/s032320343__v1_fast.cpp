#include <iostream>

#include <iomanip>

#include <string>

#include <stack>

#include <vector>

#include <math.h>

#include <stdio.h>

#include <algorithm>

#include <utility>

#include <functional>

#include <map>

#include <set>

#include <queue>

#include <list>

using namespace std;

using pii  = pair<int,int>;

using ll=long long;

using ld=long double;

#define pb push_back

#define mp make_pair

#define stpr setprecision

#define rep(i,n) for(ll i=0;i<(n);++i)

#define REP(i,a,b) for(ll i=(a);i<(b);++i)

#define crep(i) for(char i='a';i<='z';++i)

#define psortsecond(A,N) sort(A,A+N,[](const pii &a, const pii &b){return a.second<b.second;});

#define ALL(x) (x).begin(),(x).end()

#define debug(v) cout<<#v<<":";for(auto x:v){cout<<x<<' ';}cout<<endl;

#define endl '\n'

int ctoi(const char c){

  if('0' <= c && c <= '9') return (c-'0');

  return -1;

}

ll gcd(ll a,ll b){return (b == 0 ? a : gcd(b, a%b));}

ll lcm(ll a,ll b){return a*b/gcd(a,b);}

constexpr ll MOD=1000000007;

constexpr ll INF=1000000011;

constexpr ll MOD2=998244353;

constexpr ll LINF = 1001002003004005006ll;

constexpr ld EPS=10e-8;

template<class T>bool chmax(T &a, const T &b) { if (a<b) { a=b; return 1; } return 0; }

template<class T>bool chmin(T &a, const T &b) { if (b<a) { a=b; return 1; } return 0; }

template<typename T> istream& operator>>(istream& is,vector<T>& v){for(auto&& x:v)is >> x;return is;}

template<typename T,typename U> istream& operator>>(istream& is, pair<T,U>& p){ is >> p.first; is >> p.second; return is;}

template<typename T,typename U> ostream& operator>>(ostream& os, const pair<T,U>& p){ os << p.first << ' ' << p.second; return os;}

template<class T> ostream& operator<<(ostream& os, vector<T>& v){

    for(auto i=begin(v); i != end(v); ++i){

        if(i !=begin(v)) os << ' ';

        os << *i;

    }

    return os;

}



struct  UndirectedGraph{

    vector<vector<int>> g;   //グラフの各点が持つ枝の情報

    vector<int> clr;         //グラフの持つ枝の情報

    vector<int> dis;         //距離の情報

    int V;



    UndirectedGraph(int V) : V(V),

    g(vector<vector<int>>(V)),

    clr(vector<int>(V,0))

    {}



    //don't add (v,u) after adding (u,v)

    void add_edge(int u,int v){

        g[u].push_back(v);

        g[v].push_back(u);

    }





    //二部グラフ判定

    bool dfs_nib(int v,int c){

        clr[v]=c;

        for(auto x:g[v]){

            if(clr[x]==c) return false;

            if(clr[x]==0 && !dfs_nib(x,-c) ) return false;

        }

        return true;

    }

    bool isNib(){

        bool ret=true;

        for(int i=0;i<V;i++)if(clr[i]==0){

            if(!dfs_nib(i,1)){

                ret=false;break;

            }

        }

        return ret;

    }



    //distance

    void bfs(int st){

        dis=vector<int>(V,INF);

        vector<bool> checked(V,false);

        dis[st]=0;

        queue<int> q;

        q.push(st);

        while(!q.empty()){

            auto now=q.front();q.pop();

            //ここでもcontinueしないとダブる

            if(checked[now]) continue;

            checked[now]=true;

            for(auto x:g[now]){

                if(checked[x]) continue;

                dis[x]=dis[now]+1;

                q.push(x);

            }

        }

    }

};



signed main(){

    int n;

    cin>>n;

    UndirectedGraph g(n);

    char s[n][n];

    rep(i,n){

        rep(j,n){

            char t;cin>>t;

            s[i][j]=t;

            if(t=='1'&&i>j){

                g.add_edge(i,j);

            }

        }

    }

    if(!g.isNib()){

        cout<<-1<<endl;

        return 0;

    }



    int ans=0;

    rep(i,n){

        g.bfs(i);

        int x=*max_element(ALL(g.dis));

        ans=max(x,ans);

    }   

    cout<<ans+1<<endl;

    return 0;

}
