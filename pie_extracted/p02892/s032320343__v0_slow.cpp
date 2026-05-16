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

#define endl '\n'

int ctoi(const char c){

  if('0' <= c && c <= '9') return (c-'0');

  return -1;

}

long long gcd(long long a, long long b){return (b == 0 ? a : gcd(b, a%b));}

long long lcm(long long a, long long b){return a*b/gcd(a,b);}

constexpr ll MOD=1000000007;

constexpr ld EPS=10e-8;

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



ll C=0;

string S[207];

queue<int> Q;

int N;

int chek[207];

vector<int> DIS(207);

int dismax=0;



void bfs(int t){

    if(Q.empty()==1){

        return;

    }

    int h=0;

    rep(i,t){

        rep(j,N){

            if(S[Q.front()][j]=='1'){

                if(chek[j]==1 && (DIS[Q.front()]+1)%2!=DIS[j]%2){

                    cout << -1 << endl;

                    C=-1;

                    return;

                }               

                if(chek[j]==0){

                    DIS[j]=DIS[Q.front()]+1;

                    chek[j]=1;

                    h++;

                    Q.push(j);

                }

            }

        }

        Q.pop();

    }

    bfs(h);

}



void bfs2(int t,int u){

    if(Q.empty()==1){

        return;

    }

    int h=0;

    if(u>dismax){

        dismax=u;

    }

    rep(i,t){

        rep(j,N){

            if(S[Q.front()][j]=='1' && chek[j]==0){

                Q.push(j);

                chek[j]=1;

                h++;

            }

        }

        Q.pop();

    }

    bfs2(h,u+1);

}



int main(){

    cin >> N;

    rep(i,N){

        cin >> S[i];

    }

    chek[0]=1;

    DIS[0]=0;

    Q.push(0);

    bfs(1);

    if(C==-1){

        return 0;

    }

    rep(i,N){

        rep(j,N){

            chek[j]=0;

        }

        chek[i]=1;

        Q.push(i);

        bfs2(1,0);

    }

    cout << dismax+1 << endl;

}