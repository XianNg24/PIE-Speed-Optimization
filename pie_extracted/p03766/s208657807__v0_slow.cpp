#include <stdio.h>

#define R register

#define ll long long

namespace IO{

	char buf[1<<15],*S,*T;

	inline char gc(){

		if (S==T){

			T=(S=buf)+fread(buf,1,1<<15,stdin);

			if (S==T) return EOF;

		}return *S++;

	}

	inline int read(){

		R int x; R bool f; R char c;

		for (f=0; (c=gc())<'0'||c>'9'; f=c=='-');

		for (x=c^'0'; (c=gc())>='0'&&c<='9'; x=(x<<3)+(x<<1)+(c^'0'));

		return f?-x:x;

	}

}

#define MN 1000005

#define M (1<<20)

#define P 1000000007

int n,T[M<<1],ans,tt;

inline void rw(int &x,int y){x+=y; if (x>=P) x-=P;}

inline int mul(int x,int y){return (ll)x*y%P;}

inline void modify(int l,int r,int v){

	for (l+=M-1,r+=M+1; l^r^1; l>>=1,r>>=1){

		if (~l&1) rw(T[l^1],v);

		if ( r&1) rw(T[r^1],v);

	}

}

inline int query(int k){

	R int res=0;

	for (k+=M; k; k>>=1)

		rw(res,T[k]);

	return res;

}

int main(){

	n=IO::read();T[M]=1;tt=mul(n-1,n-1);

	for (R int i=0,f; i<n-1; ++i){

		f=query(i);rw(ans,mul(f,tt));rw(ans,mul(f,i+1));

		rw(T[M+i+1],f);if (i+3<=n)modify(i+3,n,f);

	}rw(ans,mul(query(n-1),n));rw(ans,query(n));

	printf("%d\n",ans);

	return 0;

}