#include <cstdio>

#include <cstdlib>

#include <cmath>

#include <cstring>



#include <iostream>

#include <complex>

#include <string>

#include <algorithm>

#include <vector>

#include <queue>

#include <stack>

#include <map>

#include <set>

#include <unordered_map>

#include <unordered_set>



#include <functional>

#include <cassert>



typedef long long ll;

using namespace std;



#define debug(x) cerr << __LINE__ << " : " << #x << " = " << (x) << endl;



#define mod 1000000007 //1e9+7(prime number)

#define INF 1000000000 //1e9

#define LLINF 2000000000000000000LL //2e18

#define SIZE 100010



ll dp[13][1<<13][10]; //桁数, 現在のエレベーター,　前の桁 



bool solve(){

  int n;

  int low[7], up[7];

  

  scanf("%d", &n);

  if(n == 0) return false;

  

  for(int i=0;i<n;i++) scanf("%d%d", low+i, up+i);



  memset(dp, 0, sizeof(dp));



  dp[0][1][0] = 1;



  ll ans = 0;



  for(int i=0;i<n*2;i++){

    for(int j=0;j<(1<<(2*n));j++){

      for(int k=0;k<10;k++){

        int next[10] = {};



        for(int l=0;l<n;l++){

          //1桁目

          if((1 << (l*2)) & j){

            for(int x=max(1,low[l]);x<=min(9, up[l]);x++)

              next[x] |= 1 << (l*2+2);

            for(int x=max(1,low[l]/10);x<=min(9,up[l]/10);x++)

              next[x] |= 1 << (l*2+1);

          }

          //2桁目

          if((1 << (l*2+1)) & j){

            for(int x=max(0,(low[l]-k*10));x<=min(9, up[l]-k*10);x++)

              next[x] |= 1 << (l*2+2);

          }

        }



        for(int l=0;l<10;l++){

          dp[i+1][next[l] & ((1 << n*2) - 1)][l] += dp[i][j][k];

          if(next[l] & (1 << (n*2))) ans += dp[i][j][k];

        }

        

      }

    }

  }

  

  cout << ans << endl;

  return true;

}



int main(){

  while(solve());

  

  return 0;

}


