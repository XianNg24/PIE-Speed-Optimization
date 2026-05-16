#include<bits/stdc++.h>

using namespace std;



int main(){

  int n,k;

  cin>>n>>k;

  int dp[n], h[n];



  for(int i=0; i<n; i++){dp[i]=999999999; cin>>h[i]; }

  dp[0]=0;

  dp[1]=abs(h[1]-h[0]);



  for(int i=0; i<n; i++){

    for(int j=1; j<=k; j++){

      if(i+j<n) dp[i+j]=min(dp[i+j], dp[i]+abs(h[i]-h[i+j]));

    }

  }



  cout<<dp[n-1];



}
